#!/usr/bin/env python3
"""从整页 PDF 截图自动裁剪每题的答案/解析区域。

动机：OCR 文字解析对公式/代码/表格还原效果差，改为答案区默认展示原书截图
（文字解析保留在图下方）。数据侧只需在 explanation 开头插入
「答案图片：answer_crops/<key>/page_NNN_<QID>_ans.jpg」行——
三端（bank SPA fillExplanation / platform AnswerExplanation / 小程序）已支持该协议。

数据流：
  data/ocr/<key>/page_NNN.json   OCR 文本块坐标（= 整页 PNG 像素坐标，run_ocr 直接喂 PNG）
  + output/questions_{key}.json  章节 a_pages / 题目 id / type（build 真理源）
  + assets/pdf_images/<key>/page_NNN.png  整页截图
  → math-bank/answer_crops/<key>/page_NNN_<QID>_ans[_pN].jpg
  → （--write-expl）把答案图片行幂等写回 output/questions_{key}.json 与 math-bank/data-{key}.json

分段规则与 parse_questions.parse_answer_page 对齐，差异：
  - 跨页续行归属当前答案（原逐页解析会把无标题续行丢弃，文字因此缺尾）；
  - 顺序单遍扫描小节全部答案页（a_pages 为小节级页范围，单题定位靠答案头）；
  - 停止条件仅限下一小节的「X.Y.Z 答案与解析」与「X.Y.Z 本节试题/习题精选」；
  - 同 (sec, qid) 重复出现时与现有 dict.update 语义一致取最后一次，并记入 dup 日志。

用法：
  python scripts/gen_answer_crops.py --course ds            # 生成裁剪图 + 抽查页
  python scripts/gen_answer_crops.py --course ds --write-expl  # 同时回写 explanation
  python scripts/gen_answer_crops.py --course ds --qids X01,A03 --dry-run
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from config import COURSE_BY_KEY, PROJECT_ROOT  # noqa: E402
from parse_patterns import (  # noqa: E402
    ANS_HEADER_RE,
    APP_ANS_START_RE,
    chapter_header_re,
    extract_answer_choice,
    is_page_noise,
    section_start_re,
)
from parse_questions import get_block_text, group_to_lines  # noqa: E402

BANK_DIR = PROJECT_ROOT / "math-bank"
REVIEW_HTML = PROJECT_ROOT / "output" / "qa" / "answer-crop-review.html"
REPORT_PATH = PROJECT_ROOT / "output" / "reports" / "answer_crops_report.json"

MAX_WIDTH = 1000          # 裁剪图最大宽度（像素），超出等比缩小
JPEG_QUALITY = 80
PAD_X = 6                 # 左右留白（页内容列全宽裁剪，覆盖 OCR 识别不到的插图/表格线）
PAD_TOP_HEADER = 8        # 答案头所在段的上方留白（避免带入上一题尾部）
PAD_TOP_CONT = 10         # 跨页续段的上方留白
PAD_BOTTOM = 14           # 下方留白
MIN_PART_H = 12           # 段最小高度，低于此视为空段跳过

# 增量门：答案侧（a_pages/answer）未变时跳过全部重裁（全量重裁 4 课约 28s，占重建一半以上）。
# 裁剪参数/算法变更时递增 ALGO_TAG 强制全量。
STATE_PATH = PROJECT_ROOT / "data" / "quality" / "answer_crop_state.json"
ALGO_TAG = "anscrop-v1"


def answers_fingerprint(src: dict) -> str:
    """答案侧输入指纹：任何影响裁剪/回写的字段变化都会改 hash。"""
    import hashlib

    h = hashlib.sha1()
    for ch in src.get("chapters", []):
        for q in ch.get("questions", []):
            h.update(
                json.dumps(
                    [
                        q.get("topic_title"),
                        q.get("id"),
                        q.get("type"),
                        q.get("a_pages"),
                        q.get("answer"),
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            )
    return h.hexdigest()

# 本小节答案区起始：X.Y.Z 答案与解析。比 parse_patterns.answer_header_re 宽松——
# OCR 会把小节号与标题之间混入 ～ ~ 等杂质（如「5.1.5～答案与解析」）。
# 注意不要加「小节号行」这类宽泛停止条件：解析正文里的 IP/版本号会被误截停
# （实测 6.4.6 的「10.1.1.2 10.1.1.5 192.1.1.0」吃掉了后 3 题答案）
_answer_header_re = re.compile(r"^\s*\d+\.\d+(?:\.\d+)?[\s～~\-—・·]*答案与解析\s*$")
# 页眉「第N章XXX」/「第N章XXX 页码」与纯页码行（跨页答案会把下一页页眉并进裁剪框，提前滤掉）
_CHAPTER_PAGE_HEADER_RE = re.compile(r"^\s*第\s*\d+\s*章")
_PAGE_NUM_RE = re.compile(r"^\s*\d{1,3}\s*$")
# explanation 中指向 answer_crops 的旧答案图片行（回写时整行替换，题目图片行不受影响）
ANSWER_CROP_LINE_RE = re.compile(
    r"^(?:答案图片|解析图片|题图|答图)\s*[：:]\s*answer_crops/", re.IGNORECASE
)


def load_ocr_pages(ocr_dir: Path, pages: list[int]) -> dict[int, list[dict]]:
    """加载答案页 OCR 行（已过滤页眉页脚），行携带整页像素坐标。"""
    out: dict[int, list[dict]] = {}
    for p in pages:
        f = ocr_dir / f"page_{p:03d}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        lines = []
        for ln in group_to_lines(get_block_text(data)):
            joined = " ".join(ln["texts"]).strip()
            if not joined or is_page_noise(joined):
                continue
            if _CHAPTER_PAGE_HEADER_RE.match(joined) or _PAGE_NUM_RE.match(joined):
                continue
            lines.append(
                {
                    "page": p,
                    "x0": ln["x0"],
                    "y0": ln["y0"],
                    "x1": ln["x1"],
                    "y1": ln["y1"],
                    "text": joined,
                }
            )
        out[p] = lines
    return out


def segment_answers(
    lines_by_page: dict[int, list[dict]],
    trace: list[str] | None = None,
    stop_heading_re: re.Pattern[str] | None = None,
) -> dict[tuple[str, str], dict]:
    """顺序扫描小节答案页流，按答案头切分，返回 (sec, qid) -> {parts, dup}。

    parts: [{page, y0, y1}]（y 已含答案头/末行范围，未加 padding）。
    trace: 可选事件日志（调试提前截停/漏题用）。
    stop_heading_re: 下一节标题行（TOC 精确节号，如 ^2\.3\s*栈…），命中即停——
    节首页顶部常带上一节答案的续行，只能按标题行切，不能按整页切。
    """
    stream: list[dict] = []
    for p in sorted(lines_by_page):
        stream.extend(lines_by_page[p])

    chapter_header = chapter_header_re()
    section_start = section_start_re()

    spans: dict[tuple[str, str], dict] = {}
    section = "choice"
    cur: dict | None = None
    started = False  # 已遇到本小节的「X.Y.Z 答案与解析」
    # 裁剪 padding 收口用：每页各答案段的 (y0,y1) 与各「新段起始行」的 y0
    seg_bounds: dict[int, list[tuple[float, float]]] = defaultdict(list)
    seg_starts: dict[int, list[float]] = defaultdict(list)

    def add_line(answer: dict, ln: dict) -> None:
        # 同页行无条件并入同段（垂直并集）：段内的大插图/表格没有 OCR 文本，
        # 只能靠上下文字行把区域撑开，按间隙判断会把图切出去
        rng = answer["pages"].setdefault(ln["page"], [ln["y0"], ln["y1"]])
        rng[0] = min(rng[0], ln["y0"])
        rng[1] = max(rng[1], ln["y1"])

    def save_cur():
        nonlocal cur
        if cur is None:
            return
        if cur["pages"]:
            key = (cur["sec"], cur["qid"])
            parts = []
            for p, rng in sorted(cur["pages"].items()):
                parts.append({"page": p, "y0": rng[0], "y1": rng[1]})
                seg_bounds[p].append((rng[0], rng[1]))
            dup = key in spans or spans.get(key, {}).get("dup", False)
            spans[key] = {"parts": parts, "dup": dup}
        cur = None

    for ln in stream:
        text = ln["text"]

        if _answer_header_re.match(text):
            if started:
                # 下一小节的答案区开始了
                if trace is not None:
                    trace.append(f"STOP p{ln['page']} answer_header: {text[:50]}")
                save_cur()
                break
            started = True
            if trace is not None:
                trace.append(f"START p{ln['page']}: {text[:50]}")
            save_cur()
            continue

        if not started:
            # 本小节答案头之前的行：上一小节的答案尾巴/题目尾巴，丢弃
            continue

        if section_start.match(text) or (stop_heading_re and stop_heading_re.match(text)):
            if trace is not None:
                trace.append(f"STOP p{ln['page']} heading: {text[:50]}")
            save_cur()
            break

        m = chapter_header.match(text)
        if m:
            if trace is not None:
                trace.append(f"SEC p{ln['page']}: {text[:40]} -> {section}")
            save_cur()
            seg_starts[ln["page"]].append(ln["y0"])
            name = m.group(1)
            section = "app" if any(w in name for w in ("综合", "解答", "应用")) else "choice"
            continue

        choice_m = extract_answer_choice(text)
        ans_m = ANS_HEADER_RE.match(text)
        if choice_m or ans_m:
            if trace is not None:
                trace.append(f"ANS p{ln['page']}: {text[:40]}")
            save_cur()
            seg_starts[ln["page"]].append(ln["y0"])
            if choice_m:
                cur = {"sec": "choice", "qid": choice_m[0], "pages": {}}
            else:
                cur = {"sec": "app", "qid": ans_m.group(1).zfill(2), "pages": {}}
            add_line(cur, ln)
            continue

        if section == "app" and cur is None and APP_ANS_START_RE.match(text):
            if trace is not None:
                trace.append(f"APP p{ln['page']}: {text[:40]}")
            m2 = APP_ANS_START_RE.match(text)
            save_cur()
            seg_starts[ln["page"]].append(ln["y0"])
            cur = {"sec": "app", "qid": m2.group(1).zfill(2), "pages": {}}
            add_line(cur, ln)
            continue

        if cur is not None:
            add_line(cur, ln)

    save_cur()
    return spans, {"bounds": seg_bounds, "starts": seg_starts}


def page_content_bounds(lines: list[dict]) -> tuple[int, int]:
    """页内容列 x 范围（全宽裁剪用，保证插图/表格线不丢）。"""
    if not lines:
        return (0, 10**9)
    return (
        max(0, int(min(ln["x0"] for ln in lines)) - PAD_X),
        int(max(ln["x1"] for ln in lines)) + PAD_X,
    )


def crop_parts(
    span: dict,
    layout: dict,
    lines_by_page: dict[int, list[dict]],
    png_dir: Path,
    key: str,
    qid: str,
    dry: bool,
) -> tuple[list[str], list[str]]:
    """裁剪一个答案的所有段，返回 (相对路径列表, 警告列表)。"""
    rels: list[str] = []
    warns: list[str] = []
    bounds_by_page: dict[int, list[tuple[float, float]]] = layout["bounds"]
    starts_by_page: dict[int, list[float]] = layout["starts"]
    part_no = 0
    for part in span["parts"]:
        part_no += 1
        page = part["page"]
        png_path = png_dir / f"page_{page:03d}.png"
        if not png_path.exists():
            warns.append(f"missing png {png_path.name}")
            continue
        y0 = part["y0"] - (PAD_TOP_HEADER if part_no == 1 else PAD_TOP_CONT)
        y1 = part["y1"] + PAD_BOTTOM
        # padding 收口：不越过同页相邻答案段的边界（段间隙常小于 padding）
        for b0, b1 in bounds_by_page.get(page, []):
            if (b0, b1) == (part["y0"], part["y1"]):
                continue  # 跳过自身
            if b1 <= part["y0"]:  # 上一段
                y0 = max(y0, b1 + 3)
            if b0 >= part["y1"]:  # 下一段
                y1 = min(y1, b0 - 3)
        for sy in starts_by_page.get(page, []):
            if part["y0"] < sy <= part["y1"]:
                # 段内包含下一段的起始行（少见）：裁到该行上方
                y1 = min(y1, sy - 3)
        if y1 - y0 < MIN_PART_H:
            warns.append(f"part {part_no} too thin ({y1 - y0:.0f}px)")
            continue
        lines = lines_by_page.get(page) or []
        x0, x1 = page_content_bounds(lines)
        suffix = "" if part_no == 1 else f"_p{part_no}"
        rel = f"answer_crops/{key}/page_{page:03d}_{qid}_ans{suffix}.jpg"
        if dry:
            rels.append(rel)
            continue
        with Image.open(png_path) as im:
            w, h = im.size
            box = (max(0, x0), max(0, int(y0)), min(w, x1), min(h, int(y1)))
            if box[3] - box[1] < MIN_PART_H:
                warns.append(f"part {part_no} clamped too thin")
                continue
            # 墨迹延展：插图/表格没有 OCR 文本，坐标并集只能到文字末行；
            # 若文字下方与下一段起始之间检测到墨迹，把下边界延伸到墨迹底部
            nxt: float | None = None
            for b0, b1 in bounds_by_page.get(page, []):
                if b0 >= part["y1"] and (b0, b1) != (part["y0"], part["y1"]):
                    nxt = b0 if nxt is None else min(nxt, b0)
            for sy in starts_by_page.get(page, []):
                if sy > part["y1"]:
                    nxt = sy if nxt is None else min(nxt, sy)
            if nxt is not None and box[3] + 8 < min(h, int(nxt) - 3):
                strip = im.crop((box[0], box[3] + 2, box[2], min(h, int(nxt) - 3))).convert("L")
                ink = strip.point(lambda p: 255 if p < 185 else 0).getbbox()
                if ink is not None and ink[3] > 8:
                    box = (box[0], box[1], box[2], min(h, box[3] + 2 + ink[3] + 6))
            crop = im.crop(box)
            if crop.width > MAX_WIDTH:
                ratio = MAX_WIDTH / crop.width
                crop = crop.resize((MAX_WIDTH, max(1, int(crop.height * ratio))), Image.LANCZOS)
            dst = PROJECT_ROOT / "math-bank" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            crop.convert("RGB").save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True)
        rels.append(rel)
    return rels, warns


def wire_explanation(exp: str, rels: list[str]) -> str:
    """把答案图片行插到 explanation 开头（幂等：替换旧 answer_crops 行，题目图片行保留）。"""
    kept = [
        ln for ln in str(exp or "").splitlines()
        if not ANSWER_CROP_LINE_RE.match(ln.strip())
    ]
    body = "\n".join(kept).strip()
    head = "\n".join(f"答案图片：{r}" for r in rels)
    return head + ("\n\n" + body if body else "")


def iter_questions(data: dict):
    for ch in data.get("chapters", []):
        for q in ch.get("questions", []):
            yield ch, q


def write_course_json(bank_dir: Path, key: str, name: str, data: dict) -> None:
    """重写 math-bank/data-<key>.json/.js/.gz（与 auto_recrop_figs.write_course 同格式）。"""
    stem = f"data-{key}"
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (bank_dir / f"{stem}.json").write_text(payload, encoding="utf-8")
    (bank_dir / f"{stem}.js").write_text(
        "// auto-generated from " + stem + ".json\n"
        "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
        f'window.__COURSE_CACHE__["{name}"] = ' + payload + ";\n",
        encoding="utf-8",
    )
    gz = bank_dir / f"{stem}.json.gz"
    if gz.exists():
        with gzip.open(gz, "wt", encoding="utf-8") as f:
            f.write(payload)


def write_review_html(items: list[dict], stats: dict, key: str, course_name: str) -> None:
    """生成本地抽查页：全部裁剪图按小节分组，人工核验裁剪质量。"""
    cards = []
    for it in items:
        srcs = "".join(
            f'<img loading="lazy" src="../math-bank/{r}" alt="{it["qid"]}" '
            f'onclick="this.classList.toggle(\'zoomed\')">'
            for r in it["rels"]
        )
        cards.append(
            f'<figure class="card" id="{it["qid"]}-{it["topic"].replace(".", "-")}">'
            f'<figcaption>{it["topic"]} · {it["qid"]} · '
            f'P{",".join(str(p) for p in it["pages"])}</figcaption>{srcs}</figure>'
        )
    html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>答案裁剪抽查 · {course_name}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#fafafa}}
h1{{font-size:18px}} .sum{{color:#666;font-size:13px;margin-bottom:12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}}
.card{{margin:0;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:8px}}
figcaption{{font-size:12px;color:#374151;margin-bottom:6px}}
.card img{{width:100%;height:auto;border:1px solid #eee;cursor:zoom-in;display:block;margin-bottom:6px}}
.card img.zoomed{{max-width:none;width:160%;}}
</style></head><body>
<h1>答案裁剪抽查 · {course_name}（{key}）</h1>
<div class="sum">共 {stats["cropped"]} 题生成 {stats["parts"]} 张裁剪图 ·
跳过 {stats["skipped"]} 题（无答案段/缺图） · 重复答案头 {stats["dup"]} 处 ·
总体积 {stats["mb"]:.1f} MB。点击图片切换 160% 放大。</div>
<div class="grid">{"".join(cards)}</div>
</body></html>"""
    REVIEW_HTML.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_HTML.write_text(html, encoding="utf-8")


def load_toc_bounds(toc_json: Path) -> tuple[dict[int, int], dict[tuple[int, int], int]]:
    """TOC → ({章号: 章首页}, {(章, 节): 节首页})，用于封顶答案页范围。"""
    data = json.loads(toc_json.read_text(encoding="utf-8"))
    chapter_starts: dict[int, int] = {}
    section_starts: dict[tuple[int, int], int] = {}
    for entry in data:
        page = int(entry[2])
        if entry[0] == 1:
            m = re.search(r"第\s*(\d+)\s*章", str(entry[1]))
            if m:
                chapter_starts[int(m.group(1))] = page
        elif entry[0] == 2:
            m = re.match(r"(\d+)\.(\d+)", str(entry[1]))
            if m:
                section_starts.setdefault((int(m.group(1)), int(m.group(2))), page)
    return chapter_starts, section_starts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--course", default="ds", choices=sorted(COURSE_BY_KEY))
    ap.add_argument("--write-expl", action="store_true", help="回写 explanation（output + math-bank data）")
    ap.add_argument("--qids", default="", help="仅处理指定题号（逗号分隔，如 X01,A03）")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 题（调试）")
    ap.add_argument("--dry-run", action="store_true", help="不写图不回写，只出统计")
    args = ap.parse_args()

    course = COURSE_BY_KEY[args.course]
    key = course.key
    only = {q.strip().upper() for q in args.qids.split(",") if q.strip()}

    src = json.loads(course.out_json.read_text(encoding="utf-8"))
    bank_path = BANK_DIR / f"data-{key}.json"
    bank_data = json.loads(bank_path.read_text(encoding="utf-8"))

    # ---- 增量门：答案侧未变且裁剪文件齐全 → 跳过重裁 ----
    # merge_courses 已用 output/questions_*.json（explanation 带答案图片行）重写过 data-*，
    # 跳过时无需补写；--qids/--limit 局部运行不进门（避免部分题误标全量态）。
    state: dict = {}
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    fingerprint = answers_fingerprint(src)
    ent = state.get(key) or {}
    if (
        not args.dry_run
        and not only
        and not args.limit
        and ent.get("algo") == ALGO_TAG
        and ent.get("hash") == fingerprint
        and ent.get("rels_by_q")  # 旧版 state（仅 flat rels）不进门，全量重裁一次自动升级
        and all((PROJECT_ROOT / "math-bank" / r).exists() for r in ent.get("rels", []))
    ):
        # 修补 data-*：fix_questions 的 CURATED_ANSWER_PATCHES 每轮都会整段重写 explanation、
        # 抹掉答案图片行（2026-09-29 incident 的修复职责在本脚本），skip 时必须代为补线，
        # 否则门内会 shipped 缺行数据。用 state 里存的关系按原 wire 逻辑补，保证字节一致。
        rels_by_q = ent["rels_by_q"]
        for _ch, q in iter_questions(bank_data):
            k = f"{q.get('topic_title') or ''}\u241f{q.get('id') or ''}"
            rels = rels_by_q.get(k)
            if rels:
                ans = q.get("answer") or {}
                ans["explanation"] = wire_explanation(ans.get("explanation") or "", rels)
                q["answer"] = ans
        # 归一化 data-* 为 write_course_json 格式，避免与 merge_courses 的 .js 包装
        # 来回翻字节（push_data 按 hash 比对，翻字节会触发无谓热更）
        write_course_json(BANK_DIR, key, course.name, bank_data)
        print(
            f"[skip] {key}: answers unchanged, {len(ent['rels'])} crops reused "
            f"(删 {STATE_PATH.name} 或改 --qids 可强制重裁)"
        )
        return

    # (topic_title, id) -> data question（用于回写 data-<key>.json）
    bank_index: dict[tuple[str, str], dict] = {}
    for _ch, q in iter_questions(bank_data):
        bank_index[(q.get("topic_title") or "", q.get("id") or "")] = q

    # 按「小节」分组（reshape 后章节按 l2×题型 拆分，但单题仍携带 topic_title + a_pages；
    # a_pages 是小节级页范围，同小节各题一致）
    topics: dict[str, dict] = {}
    for ch in src.get("chapters", []):
        for q in ch.get("questions", []):
            t = q.get("topic_title") or ""
            g = topics.setdefault(t, {"a_pages": None, "qs": []})
            g["qs"].append(q)
            ap = q.get("a_pages") or []
            if g["a_pages"] is None:
                g["a_pages"] = ap
            elif ap and ap != g["a_pages"]:
                print(f"[!] {t}: 题间 a_pages 不一致 {ap} vs {g['a_pages']}，取首见")

    ocr_cache: dict[int, list[dict]] = {}
    chapter_starts, section_starts = load_toc_bounds(course.toc_json)
    stats = {"cropped": 0, "parts": 0, "skipped": 0, "dup": 0, "wired": 0, "mb": 0.0}
    skips: list[str] = []
    review_items: list[dict] = []
    done = 0

    for topic, grp in topics.items():
        a_pages: list[int] = grp["a_pages"] or []
        if not a_pages:
            continue
        # a_pages 止于「下一节试题精选」，中间夹着下一节/下一章的知识点正文；
        # 旧逐页文字管线按页丢弃这些行，连续流却会吞进最后一个答案。
        # 处理：答案页流延伸到下一节首页为止（上一节答案常续到该页顶部），
        # 分段时遇到 TOC 精确节号的标题行即停。
        m_topic = re.match(r"^(\d+)\.(\d+)\.", topic)
        stop_heading_re = None
        page_cap = course.total_pages
        if m_topic:
            ch_num, sec_num = int(m_topic.group(1)), int(m_topic.group(2))
            next_secs = sorted((c, s) for (c, s) in section_starts if (c, s) > (ch_num, sec_num))
            if next_secs:
                nc, ns = next_secs[0]
                stop_heading_re = re.compile(rf"^\s*{nc}\.{ns}\s*[^\d.]")
                page_cap = section_starts[(nc, ns)]
            next_chs = [p for n, p in chapter_starts.items() if n > ch_num]
            if next_chs:
                page_cap = min(page_cap, min(next_chs))
        if a_pages[-1] > page_cap:
            skipped_pages = [p for p in a_pages if p > page_cap]
            a_pages = [p for p in a_pages if p <= page_cap]
            print(f"[cap] {topic}: TOC 封顶，丢弃正文页 {skipped_pages[0]}-{skipped_pages[-1]}")
        if not a_pages:
            continue
        fetched = load_ocr_pages(course.ocr_dir, [p for p in a_pages if p not in ocr_cache])
        ocr_cache.update(fetched)
        lines_by_page = {p: ocr_cache[p] for p in a_pages if p in ocr_cache}
        if not lines_by_page:
            continue
        spans, layout = segment_answers(lines_by_page, stop_heading_re=stop_heading_re)
        dup_here = sum(1 for s in spans.values() if s["dup"])
        stats["dup"] += dup_here
        if dup_here:
            print(f"[!] {topic}: {dup_here} 个重复答案头（取最后一次）")

        for q in grp["qs"]:
            qid = q.get("id") or ""
            if only and qid.upper() not in only:
                continue
            if args.limit and done >= args.limit:
                break
            done += 1
            sec = "choice" if q.get("type") == "选择题" else "app"
            seg_qid = qid[1:] if len(qid) > 1 and qid[0] in "XA" else qid
            # 拆分子问（fix_questions 拆出的 A01_2 等）与母题共用同一答案段
            seg_qid = re.sub(r"_\d+$", "", seg_qid)
            # ponytail: 运算方法解答题库号比原书综合应用题号大 2，A03 对应原书 01。
            # 库号是进度 key，不能改。不改定位的话答案图挂到 2011 年那题（原书 03）。
            # 同节 A04–A06 若抽到再同样改。
            if topic == "2.2.5 本节习题精选" and qid == "A03":
                seg_qid = "01"
            span = spans.get((sec, seg_qid))
            if not span:
                stats["skipped"] += 1
                skips.append(f"{topic} {qid}: 无答案段")
                continue
            rels, warns = crop_parts(
                span, layout, lines_by_page, course.pdf_images_dir, key, qid, args.dry_run
            )
            for w in warns:
                skips.append(f"{topic} {qid}: {w}")
            if not rels:
                stats["skipped"] += 1
                continue
            stats["cropped"] += 1
            stats["parts"] += len(rels)
            review_items.append(
                {
                    "topic": topic,
                    "qid": qid,
                    "pages": sorted({r.split("/page_")[1][:3] for r in rels}),
                    "rels": rels,
                }
            )
            if args.write_expl and not args.dry_run:
                new_exp = wire_explanation((q.get("answer") or {}).get("explanation") or "", rels)
                ans = q.get("answer") or {}
                ans["explanation"] = new_exp
                q["answer"] = ans
                dq = bank_index.get((topic, qid))
                if dq is not None:
                    dans = dq.get("answer") or {}
                    dans["explanation"] = new_exp
                    dq["answer"] = dans
                stats["wired"] += 1

    if not args.dry_run:
        for it in review_items:
            for r in it["rels"]:
                f = PROJECT_ROOT / "math-bank" / r
                if f.exists():
                    stats["mb"] += f.stat().st_size / 1024 / 1024

    if args.write_expl and not args.dry_run:
        course.out_json.write_text(
            json.dumps(src, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_course_json(BANK_DIR, key, course.name, bank_data)
        print(f"[write] {course.out_json.name} + data-{key}.json/.js/.gz")

    if not args.dry_run and not only and not args.limit:
        state[key] = {
            "algo": ALGO_TAG,
            "hash": fingerprint,
            "rels": [r for it in review_items for r in it["rels"]],
            "rels_by_q": {
                f"{it['topic']}\u241f{it['qid']}": it["rels"] for it in review_items
            },
        }
        STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    write_review_html(review_items, stats, key, course.name)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {"stats": stats, "skips": skips, "items": review_items}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )

    print(
        f"\n[{key}] 裁剪 {stats['cropped']} 题 / {stats['parts']} 张 · "
        f"跳过 {stats['skipped']} · dup {stats['dup']} · "
        f"回写 {stats['wired']} · {stats['mb']:.1f} MB"
    )
    print(f"抽查页: {REVIEW_HTML}")
    print(f"报告: {REPORT_PATH}")
    if skips:
        print(f"跳过/警告明细（前 30）:")
        for s in skips[:30]:
            print("  -", s)


if __name__ == "__main__":
    main()
