#!/usr/bin/env python3
"""单题修复：写补丁 → 单科重建 → 发布态断言，一条命令。

用法（在 apps/bank-408 目录）：
  python scripts/fix_one.py --course net --chapter 通信基础 --qid X23 --file temp/fix-X23.json
  python scripts/fix_one.py --course net --chapter 通信基础 --qid X23 --file -   < temp/fix-X23.json

408 的题号按章重复（X01… 每章重来），所以通常要给 --chapter（可只写子串，
能唯一定位即可）；不给时若题号跨章重名，脚本会列出候选章节并退出。

fix 文件是字段字典，只写要改的字段即可：
  {"content": "题干…", "options": {"C": "…"}, "choice": "C"}
也接受外层包一层 {"fields": {...}}。

补丁按 (course, chapter, qid) 合并进 data/quality/page_review_patches.json：
已有补丁的 options 逐键合并，不会抹掉同题的历史修复。随后跑
`rebuild_bank.ps1 -Course <k>`（只重建这一科），最后从 math-bank/data-<k>.json
断言新内容确实进了发布产物（不是只写进了补丁）。

--batch fixes.json 一次提交多题（一次重建、一次推送）：数组或 {"items": [...]}，
每项 {course, chapter, qid, fields}。
--dry-run 只写补丁并打印 diff；--recrop 额外强制重裁该题号的答案图
（题号跨章重名，会命中所有同号题）；--scan 重建时跑全库扫描（单题默认跳过）；
--push 在断言通过后接着热更上云。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Windows 控制台默认 GBK：管道的 JSON 和报错里的中文都要按 UTF-8 处理。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from config import COURSE_BY_KEY, PROJECT_ROOT  # noqa: E402
from quality_ledger import question_hash  # noqa: E402

import hashlib  # noqa: E402
from datetime import datetime, timezone  # noqa: E402


def _reexec_with_venv() -> None:
    """系统 python 没有 PIL 时，切到根 .venv（与 rebuild_bank.ps1 选解释器的规则一致）。"""
    try:
        import PIL  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("FIX_ONE_REEXEC") == "1":
        sys.exit("[fix_one] 当前解释器缺少 PIL，且根 .venv 不可用；先按 AGENTS.md §4 重建 .venv")
    venv_py = PROJECT_ROOT.parents[1] / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        sys.exit(f"[fix_one] 当前解释器缺少 PIL，且找不到 {venv_py}")
    os.environ["FIX_ONE_REEXEC"] = "1"
    os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])


_reexec_with_venv()

from fix_questions import OPTION_KEYS, PAGE_REVIEW_PATCH_FIELDS  # noqa: E402

PATCH_PATH = PROJECT_ROOT / "data" / "quality" / "page_review_patches.json"
EVIDENCE_PATH = PROJECT_ROOT / "data" / "quality" / "page_review_evidence.json"
PAGES_DIR = PROJECT_ROOT / "assets" / "pdf_images"
BANK_DIR = PROJECT_ROOT / "math-bank"


def norm_ws(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _ws_free(value):
    """递归去掉字符串里的所有空白，用于判断补丁是否只动了排版。"""
    if isinstance(value, str):
        return re.sub(r"\s+", "", value)
    if isinstance(value, dict):
        return {k: _ws_free(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ws_free(v) for v in value]
    return value


def _hash_payload(question: dict) -> dict:
    answer = question.get("answer") if isinstance(question.get("answer"), dict) else {}
    return {
        "id": question.get("id"),
        "type": question.get("type"),
        "content": question.get("content"),
        "options": question.get("options"),
        "answer": {"choice": answer.get("choice"), "explanation": answer.get("explanation")},
        "has_image": bool(question.get("has_image")),
        "image_ref": question.get("image_ref"),
        "q_pages": question.get("q_pages"),
        "a_pages": question.get("a_pages"),
    }


def _patched_question(old_q: dict, fields: dict) -> dict:
    q = json.loads(json.dumps(old_q))
    for key in ("content", "options", "sub_questions", "q_pages", "a_pages"):
        if key in fields:
            q[key] = fields[key]
    answer = dict(q.get("answer") or {})
    if "choice" in fields:
        answer["choice"] = fields["choice"]
    if "explanation" in fields:
        answer["explanation"] = fields["explanation"]
    q["answer"] = answer
    return q


def whitespace_only_change(old_q: dict, fields: dict) -> bool:
    """补丁是否只改了空白（断行/空格）。

    只有这类补丁能自动补断行复核记录并同步账本哈希；真改字的必须人眼对照原页。
    ``option_groups`` 改的是选项分组结构，一律走人工。
    """
    if "option_groups" in fields:
        return False
    old_payload = _hash_payload(old_q)
    new_payload = _hash_payload(_patched_question(old_q, fields))
    if old_payload == new_payload:
        return False
    return _ws_free(old_payload) == _ws_free(new_payload)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _all_hits(doc: dict, qid: str):
    return [
        (ch.get("name", ""), q)
        for ch in doc.get("chapters", [])
        for q in ch.get("questions", [])
        if str(q.get("id", "")).strip() == qid
    ]


def resolve_question(doc: dict, qid: str, chapter_hint: str = ""):
    hits = _all_hits(doc, qid)
    if not hits:
        sys.exit(f"[fix_one] 找不到题号 {qid}；先跑 python ../../tools/q_lookup.py --check \"<题干片段>\"")
    if chapter_hint:
        key = norm_ws(chapter_hint)
        narrowed = [(name, q) for name, q in hits if key in norm_ws(name)]
        if not narrowed:
            sys.exit(
                f"[fix_one] --chapter 没匹配到；{qid} 所在章节：\n  "
                + "\n  ".join(sorted({name for name, _ in hits}))
            )
        hits = narrowed
    if len(hits) > 1:
        names = "\n  ".join(sorted({name for name, _ in hits}))
        sys.exit(f"[fix_one] 题号 {qid} 在多个章节重名，用 --chapter 指定：\n  {names}")
    return hits[0]


def validate_fields(fields: dict) -> dict:
    if not isinstance(fields, dict) or not fields:
        sys.exit("[fix_one] 字段为空")
    unknown = sorted(set(fields) - PAGE_REVIEW_PATCH_FIELDS)
    if unknown:
        sys.exit(f"[fix_one] 不支持的字段 {unknown}；可用：{sorted(PAGE_REVIEW_PATCH_FIELDS)}")
    out: dict = {}
    for key, value in fields.items():
        if key == "options":
            if not isinstance(value, dict) or not value:
                sys.exit("[fix_one] options 必须是非空对象")
            bad = [k for k in value if str(k) not in OPTION_KEYS]
            if bad:
                sys.exit(f"[fix_one] 非法选项键 {bad}（只允许 A-E）")
            if any(not isinstance(v, str) or not v.strip() for v in value.values()):
                sys.exit("[fix_one] 选项值不能为空")
            out[key] = {str(k): v for k, v in value.items()}
        elif key in ("content", "explanation"):
            if not isinstance(value, str) or not value.strip():
                sys.exit(f"[fix_one] {key} 不能为空")
            out[key] = value
        elif key == "choice":
            choice = str(value).strip().upper()
            if not choice or any(c not in "ABCDE" for c in choice):
                sys.exit("[fix_one] choice 只能是 A-E（多选可写多个字母）")
            out[key] = choice
        elif key == "option_groups":
            if not isinstance(value, list) or len(value) < 2:
                sys.exit("[fix_one] option_groups 至少两组")
            out[key] = value
        elif key == "sub_questions":
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                sys.exit("[fix_one] sub_questions 只能是 null 或非空字符串数组")
            out[key] = value
    return out


def upsert_patch(payload: dict, course: str, chapter: str, qid: str, fields: dict) -> str:
    items = payload.setdefault("items", [])
    for item in items:
        if (
            str(item.get("course", "")).strip() == course
            and str(item.get("chapter", "")).strip() == chapter
            and str(item.get("qid", "")).strip() == qid
        ):
            current = item.setdefault("fields", {})
            for key, value in fields.items():
                if key == "options" and isinstance(current.get("options"), dict):
                    current["options"].update(value)
                else:
                    current[key] = value
            return "更新"
    items.append({"course": course, "chapter": chapter, "qid": qid, "fields": dict(fields)})
    return "新增"


def print_diff(old_q: dict, fields: dict) -> None:
    old_answer = old_q.get("answer") or {}
    for key, new in fields.items():
        if key == "options":
            old_options = old_q.get("options") or {}
            for k, v in new.items():
                print(f"  options.{k}: {str(old_options.get(k, ''))[:70]!r} -> {str(v)[:70]!r}")
        elif key == "choice":
            print(f"  choice: {old_answer.get('choice', '')!r} -> {new!r}")
        elif key == "content":
            print(f"  content: {str(old_q.get('content', ''))[:70]!r} -> {str(new)[:70]!r}")
        elif key == "explanation":
            print(f"  explanation: {str(old_answer.get('explanation', ''))[:70]!r} -> {str(new)[:70]!r}")
        else:
            print(f"  {key}: 已更新")


def assert_published(course: str, chapter: str, qid: str, fields: dict) -> bool:
    """从发布产物里确认补丁真的生效了。返回 False 表示该题不在发布态。"""
    pub = load_json(BANK_DIR / f"data-{course}.json")
    hit = next(
        (q for ch in pub.get("chapters", []) if str(ch.get("name", "")).strip() == chapter
         for q in ch.get("questions", [])
         if str(q.get("id", "")).strip() == qid),
        None,
    )
    if hit is None:
        print(f"[fix_one] 提示：{chapter} / {qid} 不在 data-{course}.json 里（可能被发布层过滤），跳过断言")
        return False

    problems = []
    if "content" in fields and norm_ws(hit.get("content")) != norm_ws(fields["content"]):
        problems.append(f"content 不一致：发布态={str(hit.get('content'))[:80]!r}")
    published_choice = str((hit.get("answer") or {}).get("choice", "")).strip().upper()
    if "choice" in fields and published_choice != fields["choice"]:
        problems.append(f"choice 不一致：发布态={published_choice!r}")
    if "options" in fields:
        published_options = hit.get("options") or {}
        for k, v in fields["options"].items():
            if norm_ws(published_options.get(k)) != norm_ws(v):
                problems.append(f"options.{k} 不一致：发布态={str(published_options.get(k))[:60]!r}")
    if "explanation" in fields:
        published_expl = (hit.get("answer") or {}).get("explanation") or ""
        if norm_ws(fields["explanation"]) not in norm_ws(published_expl):
            problems.append("explanation 未出现在发布态解析里")
    if problems:
        sys.exit("[fix_one] 补丁没进发布产物：\n  " + "\n  ".join(problems))
    return True


def read_version() -> str:
    html = (BANK_DIR / "index.html").read_text(encoding="utf-8")
    m = re.search(r"__BANK_DATA_VER__='(\d+)'", html)
    return m.group(1) if m else "?"


def selftest() -> None:
    payload: dict = {"items": []}
    assert upsert_patch(payload, "net", "ch", "X23", {"content": "a"}) == "新增"
    assert upsert_patch(payload, "net", "ch", "X23", {"options": {"C": "x"}}) == "更新"
    assert upsert_patch(payload, "net", "ch", "X23", {"options": {"D": "y"}}) == "更新"
    fields = payload["items"][0]["fields"]
    assert fields["content"] == "a"
    assert fields["options"] == {"C": "x", "D": "y"}, fields
    doc = {
        "chapters": [
            {"name": "网络层 · IPv4 · 选择题", "questions": [{"id": "X23"}]},
            {"name": "通信基础 · 选择题", "questions": [{"id": "X23"}]},
        ]
    }
    assert resolve_question(doc, "X23", "通信基础")[0] == "通信基础 · 选择题"
    try:
        resolve_question(doc, "X23")
    except SystemExit:
        pass
    else:
        raise AssertionError("跨章重名必须报错，不能随便挑一个")
    print("selftest ok")


def _load_entry(entry: dict) -> tuple:
    key = str(entry.get("course", "")).strip()
    if key not in COURSE_BY_KEY:
        sys.exit(f"[fix_one] 未知课程 {key!r}（可选 {sorted(COURSE_BY_KEY)}）")
    course = COURSE_BY_KEY[key]
    qid = str(entry.get("qid", "")).strip()
    if not qid:
        sys.exit("[fix_one] 缺少 qid")
    fields = validate_fields(entry.get("fields") or {})
    chapter, old_q = resolve_question(load_json(course.out_json), qid, str(entry.get("chapter", "")).strip())
    return course, chapter, qid, fields, old_q


def sync_local_platform_pool() -> None:
    """题目改了就重导本机平台 408 题池，否则本机 /practice 与 q_lookup 还看到旧文本。"""
    script = PROJECT_ROOT.parent / "platform-v2" / "backend" / "scripts" / "import_408_banks.py"
    venv_py = PROJECT_ROOT.parents[1] / ".venv" / "Scripts" / "python.exe"
    if not (script.exists() and venv_py.exists()):
        return
    try:
        out = subprocess.run(
            [str(venv_py), str(script)], cwd=str(script.parent.parent),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        print(f"[fix_one] 提示：本机平台题池未重导（{exc}）；手动跑 {venv_py} {script}")
        return
    lines = [ln for ln in (out.stdout or "").splitlines() if ln.strip()]
    if out.returncode == 0 and lines:
        print(f"[fix_one] 本机平台题池已重导：{lines[-1]}")
    else:
        print(f"[fix_one] 提示：本机平台题池重导失败；手动跑 {venv_py} {script}")


def _published_question(course, chapter: str, qid: str):
    data = load_json(BANK_DIR / f"data-{course.key}.json")
    for ch in data.get("chapters") or []:
        if str(ch.get("name")) != chapter:
            continue
        for question in ch.get("questions") or []:
            if str(question.get("id")) == qid:
                return question
    return None


def _page_records(course, numbers):
    """把页号换成「页图路径 + sha256」；有任何一页缺图就返回 None，不伪造已查看。"""
    out = []
    for number in numbers or []:
        path = PAGES_DIR / course.key / f"page_{int(number):03d}.png"
        if not path.is_file():
            return None
        out.append({
            "path": f"apps/bank-408/{path.relative_to(PROJECT_ROOT).as_posix()}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return out


def certify_layout_patches(resolved: list) -> list[str]:
    """只改断行/空白的补丁：补排版复核记录并把账本哈希同步到当前发布态。

    真改字的题一律不自动同步——热更门禁会拦下，提示人工对照原页。
    """
    evidence = load_json(EVIDENCE_PATH)
    records = evidence.get("records")
    if not isinstance(records, list):
        sys.exit("[fix_one] page_review_evidence.json 结构异常")
    known = {
        (str(r.get("source_uid")), str(r.get("source_hash")), str(r.get("final_action")))
        for r in records if isinstance(r, dict)
    }
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    uids: list[str] = []
    skipped: list[str] = []
    for course, chapter, qid, fields, old_q in resolved:
        if not whitespace_only_change(old_q, fields):
            skipped.append(f"{course.key} {qid}")
            continue
        question = _published_question(course, chapter, qid)
        if question is None:
            skipped.append(f"{course.key} {qid}（发布态找不到）")
            continue
        q_pages = _page_records(course, question.get("q_pages"))
        a_pages = _page_records(course, question.get("a_pages"))
        if q_pages is None or a_pages is None:
            skipped.append(f"{course.key} {qid}（页图缺失）")
            continue
        uid = f"408:cs408-{course.key}::{chapter}::{qid}"
        digest = question_hash(question)
        if (uid, digest, "patch") not in known:
            records.append({
                "source_uid": uid,
                "protocol": "codex-original-page-review-v1",
                "reviewer": "fix_one",
                "reviewed_at": now,
                "q_pages_viewed": q_pages,
                "a_pages_viewed": a_pages,
                "final_action": "patch",
                "content_match": True,
                "options_match": True,
                "answer_match": True,
                "explanation_match": True,
                "image_match": True,
                "detected_errors": [],
                "rationale": "排版复核：补丁只改断行/空白，题干、选项、答案与解析逐字未变。",
                "source_hash": digest,
                "post_patch_verified": True,
            })
            known.add((uid, digest, "patch"))
        uids.append(uid)
    if uids:
        evidence["updated_at"] = now
        EVIDENCE_PATH.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        from apply_page_review_certifications import apply as apply_certifications

        result = apply_certifications(sync_uids=set(uids))
        print(f"[fix_one] 排版补丁自动复核 {len(uids)} 题，账本哈希已同步"
              f"（synced={result.get('synced')}）")
    if skipped:
        print("[fix_one] 未自动同步（文字有改动，需人工对照原页复核）：" + "、".join(skipped))
    return uids


def apply_and_build(entries: list, *, recrop: bool = False, dry_run: bool = False,
                    scan: bool = False, push: bool = False) -> int:
    resolved = [_load_entry(entry) for entry in entries]

    payload = load_json(PATCH_PATH)
    for course, chapter, qid, fields, old_q in resolved:
        print(f"[fix_one] {course.short} / {chapter} / {qid}")
        print_diff(old_q, fields)
        action = upsert_patch(payload, course.key, chapter, qid, fields)
        print(f"[fix_one] 补丁{action}：{PATCH_PATH.name}")
    PATCH_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if dry_run:
        print("[fix_one] --dry-run：未重建")
        return 0

    courses = {course.key for course, *_ in resolved}
    before = read_version()
    print(f"[fix_one] 重建中（{'全部四科' if len(courses) > 1 else next(iter(courses))}）…")
    cmd = ["powershell", "-File", str(PROJECT_ROOT / "scripts" / "rebuild_bank.ps1")]
    if len(courses) == 1:
        cmd += ["-Course", next(iter(courses))]
    if not scan:
        cmd += ["-SkipScan"]
    if recrop:
        cmd += ["-Qids", resolved[0][2]]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)

    for course, chapter, qid, fields, _ in resolved:
        assert_published(course.key, chapter, qid, fields)
    after = read_version()
    print(f"[fix_one] 发布态断言通过（{len(resolved)} 题）；缓存戳 {before} -> {after}")
    certify_layout_patches(resolved)
    gate = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "quality_ledger.py"),
         "--refresh-hashes", "--check-published"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if gate.returncode != 0:
        tail = [ln for ln in (gate.stdout or "").splitlines() if ln.strip()][-6:]
        print("[fix_one] 发布态门禁未过（push_data.ps1 会拒绝推送）：")
        for line in tail:
            print("  " + line)
    else:
        print("[fix_one] 发布态门禁通过（check-published 0 问题）")
    sync_local_platform_pool()
    for course, chapter, qid, _, _ in resolved:
        print(
            "[fix_one] 本机核对："
            f"http://127.0.0.1:8080/?course={quote(course.name)}"
            f"&chapter={quote(chapter)}&q={quote(qid)}"
        )

    if push:
        subprocess.run(
            ["powershell", "-File", str(PROJECT_ROOT / "scripts" / "push_data.ps1")],
            cwd=PROJECT_ROOT, check=True,
        )
    else:
        print("[fix_one] 下一步：powershell -File scripts/push_data.ps1（或加 --push 一步到位）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", required=False, choices=sorted(COURSE_BY_KEY))
    ap.add_argument("--qid", required=False)
    ap.add_argument("--chapter", default="", help="章节名（可子串）；题号跨章重名时必填")
    ap.add_argument("--file", help="字段 JSON 路径，- 表示 stdin")
    ap.add_argument("--batch", help="批量 JSON：数组或 {\"items\": [...]}，每项 {course, chapter, qid, fields}")
    ap.add_argument("--recrop", action="store_true",
                    help="强制重裁该题号的答案图（会命中同题号的所有章节，只在图本身有问题时用）")
    ap.add_argument("--dry-run", action="store_true", help="只写补丁，不重建")
    ap.add_argument("--scan", action="store_true", help="重建时跑全库扫描（单题默认跳过）")
    ap.add_argument("--push", action="store_true", help="断言通过后跑 push_data.ps1")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return 0

    if args.batch:
        if args.recrop:
            ap.error("--recrop 不能和 --batch 一起用")
        raw = sys.stdin.read() if args.batch == "-" else Path(args.batch).read_text(encoding="utf-8")
        data = json.loads(raw)
        entries = data.get("items") if isinstance(data, dict) else data
        if not isinstance(entries, list) or not entries:
            ap.error("--batch 需要一个非空数组")
    else:
        if not (args.course and args.qid and args.file):
            ap.error("需要 --course / --qid / --file，或 --batch（或 --selftest）")
        raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        data = json.loads(raw)
        fields = validate_fields(data.get("fields") if isinstance(data, dict) and "fields" in data else data)
        entries = [{"course": args.course, "chapter": args.chapter, "qid": args.qid, "fields": fields}]

    return apply_and_build(
        entries, recrop=args.recrop, dry_run=args.dry_run, scan=args.scan, push=args.push
    )


if __name__ == "__main__":
    raise SystemExit(main())
