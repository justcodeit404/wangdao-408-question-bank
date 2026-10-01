# -*- coding: utf-8 -*-
"""
408 有图题自动重裁：用 OCR 定「题干底 / 选项顶」+ 墨迹连通域抠图，
不再整题 bbox 硬切。

用法:
  python apps/bank-408/scripts/auto_recrop_figs.py              # 全量
  python apps/bank-408/scripts/auto_recrop_figs.py --course ds
  python apps/bank-408/scripts/auto_recrop_figs.py --dry-run
  python apps/bank-408/scripts/auto_recrop_figs.py --only ds:101:X16
  python apps/bank-408/scripts/auto_recrop_figs.py --report temp/fig-recrop-report.json

写回:
  math-bank/crops/{course}/page_XXX_ID.png
  math-bank/data-*.json / .js / .json.gz（若已有 gz）
  output/qa/fig-review-data.json（若存在审查页数据）
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "math-bank"
PDF_ROOT = ROOT / "assets" / "pdf_images"
OCR_ROOT = ROOT / "data" / "ocr"
REPO_TEMP = ROOT.parents[1] / "temp"

COURSE_META = {
    "ds": ("数据结构", "data-ds"),
    "coa": ("计算机组成原理", "data-coa"),
    "os": ("操作系统", "data-os"),
    "net": ("计算机网络", "data-net"),
}

FIG_MARK = ("如下图", "下图所示", "右图", "左图", "如图", "下图", "见下图", "上图")
RIGHT_MARK = ("右图", "右下图", "右上图")
LEFT_MARK = ("左图", "左下图", "左上图")

OPT_RE = re.compile(r"^[A-Da-dＡ-Ｄ][\.．、\)）]")
CIRCLED_OPT_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]|[①②③④⑤⑥⑦⑧⑨⑩].*[①②③④⑤⑥⑦⑧⑨⑩]")
NEXT_Q_RE = re.compile(r"^\d{1,3}\s*[\.．、]|^\d{1,3}．")
# 图注：短、数字串、中文标签
LABELISH_RE = re.compile(
    r"^[\d\s,，、\-–—:~～\.]+$|"
    r"^(入口|出口|轨道|图|示意|顶|底|左|右|上|下|"
    r"队头|队尾|栈顶|栈底|root|null|NULL|T|F|"
    r"进程|资源|请求|分配|边|点|权)[\w\u4e00-\u9fff]{0,6}$",
    re.I,
)


def looks_fig(q: dict) -> tuple[bool, str]:
    content = q.get("content") or ""
    opts = q.get("options") or {}
    ref = q.get("image_ref") or {}
    cropped = ref.get("cropped") if isinstance(ref, dict) else None
    exp = ""
    ans = q.get("answer")
    if isinstance(ans, dict):
        exp = ans.get("explanation") or ""
    m = re.search(r"(?:题目图片|题图)\s*[：:]\s*(\S+)", exp)
    if m and not cropped:
        cropped = m.group(1).strip()
    ok = bool(
        q.get("has_image")
        or cropped
        or any(x in content for x in FIG_MARK)
        or (
            isinstance(opts, dict)
            and opts
            and all("见图" in str(v) for v in opts.values())
        )
        or m
    )
    return ok, (cropped or "").replace("\\", "/")


def load_ocr(course: str, page: int) -> list[dict]:
    p = OCR_ROOT / course / f"page_{int(page):03d}.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return list(data.get("blocks") or [])


def _nw(s: str | None) -> str:
    return re.sub(r"\s+", "", s or "")


CJK_PUNCT_RE = re.compile(r"[。？！；：，、『』「」【】（）《》〈〉]")
FRAG_PUNCT_RE = re.compile(r"[。？！；：?!]")


def _is_fig_annotation(
    text: str, x0: float | None = None, qx0: float | None = None
) -> bool:
    """图内标注行：无全角句读、较短（如 'seq=601,ack_seq=501' '时间V'）。

    正文折行几乎总带全角标点；无标点的较长正文行再靠「中文占比高且
    起始 x 靠近题左栏」排除（如 '设 str1 和 str2 分别指向…' 是正文）。
    """
    t = (text or "").strip()
    if not t or len(_nw(t)) > 40:
        return False
    if CJK_PUNCT_RE.search(t):
        return False
    if _is_option_line(t) or NEXT_Q_RE.match(t):
        return False
    if len(_nw(t)) <= 8:
        return True
    cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
    if cjk / max(1, len(_nw(t))) < 0.4:
        return True
    if x0 is not None and qx0 is not None and x0 > qx0 + 60:
        return True
    return False


def _is_body_line(text: str) -> bool:
    t = (text or "").strip()
    if len(t) >= 18:
        return True
    # 中等长度且含题干语气
    if len(t) >= 10 and any(
        k in t
        for k in ("下列", "已知", "设有", "若", "则", "正确", "错误", "是（", "为（")
    ):
        return True
    return False


def _is_option_line(text: str) -> bool:
    t = (text or "").strip()
    if OPT_RE.match(t) or CIRCLED_OPT_RE.search(t):
        return True
    # 同行多选项 "A. 2  B.3  C.4  D.5"
    if (
        re.search(r"[A-D][\.．、]\s*\S+", t)
        and len(re.findall(r"[A-D][\.．、]", t)) >= 2
    ):
        return True
    return False


def marker_band_box(
    gray: np.ndarray,
    blocks: list[dict],
    q_bbox: list[float] | None,
    content: str,
) -> tuple[tuple[int, int, int, int] | None, dict]:
    """Find a figure placed between a ``如下图`` stem and the next text band.

    A large share of the books' figures sit *inside* the question bbox, between
    two text paragraphs.  Using the last body line as the figure start therefore
    skips the real figure and lands on the following question.  Anchor the band
    to the OCR line that actually contains the image marker instead.
    """
    meta: dict = {"mode": "marker_band"}
    if not q_bbox or len(q_bbox) != 4:
        meta["reject"] = "no_question_bbox"
        return None, meta

    # Literal left/right layouts need horizontal reasoning handled by the
    # existing detector.  This helper is deliberately conservative.
    if any(m in (content or "") for m in RIGHT_MARK + LEFT_MARK):
        meta["reject"] = "side_figure"
        return None, meta

    h, w = gray.shape
    qx0, qy0, qx1, qy1 = [float(v) for v in q_bbox]
    in_question = [
        b
        for b in blocks
        if float(b["y1"]) >= qy0 - 8
        and float(b["y0"]) <= qy1 + 8
        and float(b["x1"]) >= qx0 - 20
        and float(b["x0"]) <= qx1 + 20
    ]
    in_question.sort(key=lambda b: (float(b["y0"]), float(b["x0"])))
    markers = [
        b
        for b in in_question
        if any(m in (b.get("text") or "") for m in FIG_MARK)
    ]
    if not markers:
        meta["reject"] = "marker_not_in_ocr"
        return None, meta

    marker = markers[0]
    stem_end = float(marker["y1"])

    # A wrapped sentence can continue for one or more tightly adjacent OCR
    # lines after the marker line (e.g. DS page 46 question 17).
    for b in in_question:
        by0, by1 = float(b["y0"]), float(b["y1"])
        if by0 < float(marker["y0"]):
            continue
        if by0 <= stem_end + 12 and by1 > stem_end and _is_body_line(b.get("text") or ""):
            stem_end = by1

    boundaries = []
    for b in in_question:
        by0 = float(b["y0"])
        if by0 <= stem_end + 12:
            continue
        text = (b.get("text") or "").strip()
        # 选项行/下一题题号永远是边界；正文行若是图内标注样式
        # （无全角句读、短）则不当边界——它是图的一部分（如"seq=601,…"），
        # 误当边界会把图截断（net:257:X56）。
        if _is_option_line(text) or NEXT_Q_RE.match(text):
            boundaries.append(by0)
        elif _is_body_line(text) and not _is_fig_annotation(
            text, float(b["x0"]), qx0
        ):
            boundaries.append(by0)

    if not boundaries:
        meta["reject"] = "no_lower_text_boundary"
        return None, meta

    lower = min(boundaries)
    if lower - stem_end < 34:
        meta["reject"] = "band_too_short"
        return None, meta

    region = (
        max(0, int(qx0) - 12),
        max(0, int(stem_end) + 1),
        min(w, int(qx1) + 12),
        min(h, int(lower) - 2),
    )
    meta["region"] = list(region)
    meta["marker_text"] = (marker.get("text") or "")[:80]
    meta["stem_end"] = stem_end
    meta["lower_text"] = lower

    box = ink_bbox(
        gray,
        region,
        thr=218,
        row_frac=0.003,
        col_frac=0.002,
        pad=10,
        max_h=max(80, region[3] - region[1]),
    )
    if box:
        box = (
            max(region[0], box[0]),
            max(region[1], box[1]),
            min(region[2], box[2]),
            min(region[3], box[3]),
        )
    if not box or box[2] - box[0] < 40 or box[3] - box[1] < 30:
        meta["reject"] = "no_figure_ink"
        return None, meta
    meta["box"] = list(box)
    return box, meta


def _neighbor_y_bounds(
    page_boxes: list[tuple[float, float]] | None,
    own_bbox: list[float] | None,
    page_h: int,
) -> tuple[float, float]:
    """本题在同页题 bbox 中的纵向领土：(上方最近邻题底, 下方最近邻题顶)。

    与自身区间相交的框（自身或膨胀过的邻题）不参与约束。
    """
    if own_bbox and len(own_bbox) == 4:
        own_y0 = float(own_bbox[1])
        own_y1 = min(float(own_bbox[3]), float(page_h))
    else:
        own_y0, own_y1 = 0.0, float(page_h)
    lo, hi = 0.0, float(page_h)
    for y0, y1 in page_boxes or []:
        if y1 <= own_y0 + 20:
            lo = max(lo, y1)
        elif y0 >= own_y1 - 20:
            hi = min(hi, y0)
    return lo, hi


def strip_fig_fragments(
    content: str, region, blocks: list[dict]
) -> tuple[str, list[str]]:
    """剥除 content 中落在图区内的 OCR 标注行（带句读守卫防误删正文）。

    匹配 = content 行去空白后与图区内某 OCR 行（或同行拼接）完全一致；
    守卫 = 无句读标点、非【开头、非 N）子问题、非选项、非下一题题号。
    """
    if not content or not region or len(region) != 4:
        return content, []
    rx0, ry0, rx1, ry1 = [float(v) for v in region]
    cand = [
        b
        for b in blocks
        if rx0 <= (float(b["x0"]) + float(b["x1"])) / 2 <= rx1
        and ry0 <= (float(b["y0"]) + float(b["y1"])) / 2 <= ry1
        and (b.get("text") or "").strip()
    ]
    cand.sort(key=lambda b: ((float(b["y0"]) + float(b["y1"])) / 2, float(b["x0"])))
    groups: list[list[dict]] = []
    for b in cand:
        cy = (float(b["y0"]) + float(b["y1"])) / 2
        if groups:
            g0 = groups[-1][0]
            gcy = (float(g0["y0"]) + float(g0["y1"])) / 2
            if abs(cy - gcy) < 14:
                groups[-1].append(b)
                continue
        groups.append([b])
    rows: set[str] = set()
    for g in groups:
        g.sort(key=lambda b: float(b["x0"]))
        rows.add("".join(_nw(b.get("text")) for b in g))
        for b in g:
            rows.add(_nw(b.get("text")))

    kept: list[str] = []
    stripped: list[str] = []
    for ln in content.splitlines():
        t = _nw(ln)
        s = ln.strip()
        if (
            t
            and len(t) <= 40
            and t in rows
            and not CJK_PUNCT_RE.search(ln)
            and not FRAG_PUNCT_RE.search(ln)
            and "的" not in ln
            and not ln.rstrip().endswith((",", "，", "、"))
            and not s.startswith("【")
            and not re.match(r"^\d+[）)]", s)
            and not _is_option_line(ln)
            and not NEXT_Q_RE.match(s)
        ):
            stripped.append(ln)
            continue
        kept.append(ln)
    if not stripped:
        return content, []
    return "\n".join(kept).strip("\n"), stripped


def question_fallback_box(
    q_bbox: list[float] | None, page_w: int, page_h: int, pad: int = 10
) -> tuple[int, int, int, int] | None:
    """Return a safe full-row crop containing only the current question.

    OCR question bboxes describe text, so a literal right-side figure can sit
    outside their x range.  Keep the reliable question y range but expand to
    the book's full content width.
    """
    if not q_bbox or len(q_bbox) != 4:
        return None
    x0, y0, x1, y1 = [int(float(v)) for v in q_bbox]
    page_margin = max(20, int(page_w * 0.06))
    box = (
        max(0, min(x0 - pad, page_margin)),
        max(0, y0 - pad),
        min(page_w, max(x1 + pad, page_w - page_margin)),
        min(page_h, y1 + pad),
    )
    if box[2] - box[0] < 40 or box[3] - box[1] < 30:
        return None
    return box


def ocr_box_coverage(
    box: tuple[int, int, int, int], blocks: list[dict]
) -> float:
    """Approximate how much of a candidate is covered by OCR text boxes."""
    x0, y0, x1, y1 = box
    area = max(1, (x1 - x0) * (y1 - y0))
    covered = 0.0
    for b in blocks:
        ix0 = max(float(x0), float(b["x0"]))
        iy0 = max(float(y0), float(b["y0"]))
        ix1 = min(float(x1), float(b["x1"]))
        iy1 = min(float(y1), float(b["y1"]))
        if ix1 > ix0 and iy1 > iy0:
            covered += (ix1 - ix0) * (iy1 - iy0)
    return min(1.0, covered / area)


def overlaps_option_text(
    box: tuple[int, int, int, int], blocks: list[dict]
) -> bool:
    x0, y0, x1, y1 = box
    for b in blocks:
        if not _is_option_line(b.get("text") or ""):
            continue
        ix0 = max(float(x0), float(b["x0"]))
        iy0 = max(float(y0), float(b["y0"]))
        ix1 = min(float(x1), float(b["x1"]))
        iy1 = min(float(y1), float(b["y1"]))
        if ix1 > ix0 and iy1 > iy0:
            return True
    return False


def question_ocr_bbox(
    qid: str,
    q_bbox: list[float] | None,
    blocks: list[dict],
    page_w: int,
    page_h: int,
) -> tuple[list[float] | None, bool]:
    """Expand a choice question to the next printed question number.

    Parser text bboxes sometimes stop before a diagram placed after the answer
    choices.  Printed question numbers provide a much safer vertical boundary.
    The boolean indicates a question continuing onto the next page.
    """
    m = re.match(r"^[XAxa]\s*0*(\d+)", str(qid or "").strip())
    if not m:
        return q_bbox, False
    number = int(m.group(1))
    cur_re = re.compile(rf"^0*{number}\s*[\.．、]")
    next_re = re.compile(rf"^0*{number + 1}\s*[\.．、]")
    ordered = sorted(blocks, key=lambda b: (float(b["y0"]), float(b["x0"])))
    # 题号必在左栏（x0 小），排除正文里的 "3." 之类假匹配（ds:248:A03）
    starts = [
        b
        for b in ordered
        if float(b["x0"]) < 260 and cur_re.match((b.get("text") or "").strip())
    ]
    if not starts:
        return q_bbox, False
    if q_bbox and len(q_bbox) == 4:
        anchor = float(q_bbox[1])
        current = min(starts, key=lambda b: abs(float(b["y0"]) - anchor))
    else:
        current = starts[0]
    y0 = float(current["y0"])
    following = [
        b
        for b in ordered
        if float(b["y0"]) > y0 + 20
        and float(b["x0"]) < 260
        and next_re.match((b.get("text") or "").strip())
    ]
    if following:
        y1 = min(float(b["y0"]) for b in following) - 5
        continues = False
    else:
        y1 = page_h - 30
        continues = y0 > page_h * 0.72
    x0 = float(q_bbox[0]) if q_bbox and len(q_bbox) == 4 else 70.0
    x1 = float(q_bbox[2]) if q_bbox and len(q_bbox) == 4 else page_w - 70.0
    return [x0, y0, x1, y1], continues


def carryover_top_figure_box(
    gray: np.ndarray, blocks: list[dict]
) -> tuple[tuple[int, int, int, int] | None, dict]:
    """Crop a figure continued at the top of the following book page."""
    h, w = gray.shape
    ordered = sorted(blocks, key=lambda b: (float(b["y0"]), float(b["x0"])))
    option_ys = [
        float(b["y0"])
        for b in ordered
        if 120 < float(b["y0"]) < h * 0.55 and _is_option_line(b.get("text") or "")
    ]
    if not option_ys:
        return None, {"mode": "cross_page", "reject": "no_top_options"}
    option_top = min(option_ys)
    top = 130.0
    # Skip continuation prose above the carried figure.
    for b in ordered:
        by0, by1 = float(b["y0"]), float(b["y1"])
        if by0 < 125 or by0 >= option_top:
            continue
        if _is_body_line(b.get("text") or "") and by0 <= top + 90:
            top = max(top, by1 + 3)
    region = (55, int(top), w - 55, int(option_top) - 3)
    box = ink_bbox(
        gray,
        region,
        thr=218,
        row_frac=0.003,
        col_frac=0.002,
        pad=10,
        max_h=max(80, region[3] - region[1]),
    )
    meta = {"mode": "cross_page", "region": list(region), "option_top": option_top}
    if not box:
        meta["reject"] = "no_figure_ink"
        return None, meta
    box = (
        max(region[0], box[0]),
        max(region[1], box[1]),
        min(region[2], box[2]),
        min(region[3], box[3]),
    )
    if box[2] - box[0] < 120 or box[3] - box[1] < 60:
        meta["reject"] = "too_small"
        return None, meta
    return box, meta


def _is_labelish(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 24:
        return False
    if _is_option_line(t) or _is_body_line(t) or NEXT_Q_RE.match(t):
        return False
    if LABELISH_RE.match(t):
        return True
    # 短中文/符号（图注常见）
    if len(t) <= 8 and not re.search(r"[。？！；]", t):
        # 排除纯题号残留
        if re.match(r"^\d{1,2}$", t):
            return False
        return True
    return False


def classify_blocks(
    blocks: list[dict],
    q_bbox: list[float] | None,
    page_h: int,
    y_bound: float | None = None,
):
    if q_bbox and len(q_bbox) == 4:
        qx0, qy0, qx1, qy1 = [float(v) for v in q_bbox]
        # 上缘只留 8px 余量：bbox 顶即题号行，余量大了会把上一题
        # 的选项行泄进 opts，误判 fig_after_options（ds:244:X22 等）。
        y0 = max(0, qy0 - 8)
        y1 = min(page_h, qy1 + 80)
        if y_bound is not None and y_bound - 5 > qy0:
            # 邻题顶边界：防止把下一题的文本当本题的题干/选项
            y1 = min(y1, y_bound - 5)
    else:
        y0, y1 = 0, page_h

    stem, opts, labels, others = [], [], [], []
    q_top = float(q_bbox[1]) if q_bbox and len(q_bbox) == 4 else 0.0
    for b in blocks:
        by0, by1 = float(b["y0"]), float(b["y1"])
        # 中心点过滤：跨边界的块（中心在窗外）不算本题内容
        cy = 0.5 * (by0 + by1)
        if cy < y0 or cy > y1:
            continue
        t = (b.get("text") or "").strip()
        if not t:
            continue
        if _is_option_line(t):
            opts.append(b)
        elif NEXT_Q_RE.match(t) and by0 > (q_top + 40):
            # 可能是下一题题号——当选项下界
            others.append(b)
        elif _is_body_line(t):
            stem.append(b)
        elif _is_labelish(t):
            labels.append(b)
        else:
            others.append(b)
    return stem, opts, labels, others


def _dilate(mask: np.ndarray, iters: int = 2) -> np.ndarray:
    m = mask.astype(np.uint8)
    for _ in range(iters):
        m2 = m.copy()
        m2[1:, :] |= m[:-1, :]
        m2[:-1, :] |= m[1:, :]
        m2[:, 1:] |= m[:, :-1]
        m2[:, :-1] |= m[:, 1:]
        m = m2
    return m.astype(bool)


def _largest_component_bbox(
    mask: np.ndarray, min_area: int = 80
) -> tuple[int, int, int, int] | None:
    """4-connected components; return bbox of largest (ry0,ry1,cx0,cx1) in mask coords."""
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    best = None
    best_area = 0
    ys, xs = np.where(mask)
    # seed from dark pixels; limit work
    if len(ys) == 0:
        return None
    # subsample seeds if huge
    step = max(1, len(ys) // 8000)
    for sy, sx in zip(ys[::step], xs[::step]):
        if visited[sy, sx] or not mask[sy, sx]:
            continue
        stack = [(int(sy), int(sx))]
        visited[sy, sx] = True
        miny = maxy = int(sy)
        minx = maxx = int(sx)
        area = 0
        while stack:
            y, x = stack.pop()
            area += 1
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))
        if area >= min_area and area > best_area:
            best_area = area
            best = (miny, maxy + 1, minx, maxx + 1)
    return best


def ink_bbox(
    gray: np.ndarray,
    region: tuple[int, int, int, int],
    thr: int = 205,
    row_frac: float = 0.008,
    col_frac: float = 0.006,
    pad: int = 8,
    use_cc: bool = True,
    max_h: int | None = None,
    max_w: int | None = None,
) -> tuple[int, int, int, int] | None:
    """region = x0,y0,x1,y1. Return tight ink box in page coords or None."""
    h, w = gray.shape
    x0, y0, x1, y1 = region
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 - x0 < 12 or y1 - y0 < 12:
        return None
    roi = gray[y0:y1, x0:x1]
    mask = roi < thr
    if mask.mean() < 0.0015:
        return None

    # 线稿图（轨道/电路）稀疏，投影比最大连通域更稳
    mask = _dilate(mask, 3)

    row_ink = mask.mean(axis=1)
    col_ink = mask.mean(axis=0)
    rows = np.where(row_ink > row_frac)[0]
    cols = np.where(col_ink > col_frac)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    ry0, ry1 = int(rows[0]), int(rows[-1]) + 1
    cx0, cx1 = int(cols[0]), int(cols[-1]) + 1

    # 去掉上下/左右边缘的孤立细噪声带（连续低密度行）
    def _trim_sparse(lo, hi, dens, thr):
        while lo < hi - 8 and dens[lo] < thr * 0.5:
            lo += 1
        while hi > lo + 8 and dens[hi - 1] < thr * 0.5:
            hi -= 1
        return lo, hi

    ry0, ry1 = _trim_sparse(ry0, ry1, row_ink, row_frac)
    cx0, cx1 = _trim_sparse(cx0, cx1, col_ink, col_frac)

    if max_h and ry1 - ry0 > max_h:
        # 取密度最高的 max_h 窗口
        win = max_h
        best_s, best_i = -1.0, ry0
        for i in range(ry0, max(ry0 + 1, ry1 - win + 1)):
            s = float(row_ink[i : i + win].sum())
            if s > best_s:
                best_s, best_i = s, i
        ry0, ry1 = best_i, best_i + win
    if max_w and cx1 - cx0 > max_w:
        mid = (cx0 + cx1) // 2
        cx0, cx1 = mid - max_w // 2, mid + max_w // 2

    bx0 = x0 + cx0 - pad
    by0 = y0 + ry0 - pad
    bx1 = x0 + cx1 + pad
    by1 = y0 + ry1 + pad
    return (
        max(0, bx0),
        max(0, by0),
        min(w, bx1),
        min(h, by1),
    )


def union_boxes(
    boxes: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return x0, y0, x1, y1


def expand_with_labels(
    box: tuple[int, int, int, int],
    labels: list[dict],
    margin: float = 28,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    kept = [box]
    for b in labels:
        bx0, by0, bx1, by1 = (
            float(b["x0"]),
            float(b["y0"]),
            float(b["x1"]),
            float(b["y1"]),
        )
        # near the ink box?
        cx = 0.5 * (bx0 + bx1)
        cy = 0.5 * (by0 + by1)
        near = x0 - margin <= cx <= x1 + margin and y0 - margin <= cy <= y1 + margin
        # or vertically between stem and opts already in band
        if near:
            kept.append((int(bx0) - 4, int(by0) - 4, int(bx1) + 4, int(by1) + 4))
    u = union_boxes(kept)
    return u or box


def _side_figure_box(
    gray: np.ndarray,
    blocks: list[dict],
    q_bbox4: tuple[float, float, float, float],
    text_blocks: list[dict],
    side: str,
    meta: dict,
) -> tuple[int, int, int, int] | None:
    """右图/左图定位：文本栏之外的墨迹行聚簇。

    侧图可与多道题的文字同高并列（树挂在右栏跨越 X37/X38 文本带），
    纵向邻题边界不适用。做法：侧栏内先掩掉正文/选项/题号文本像素，
    再按墨迹行聚簇（间隙 >20px 断开），选「顶部离题干顶最近且足够高」的簇。
    """
    h, w = gray.shape
    qx0, qy0, qx1, qy1 = q_bbox4
    if side == "right":
        zx0, zx1 = int(w * 0.42), w - 24
    else:
        zx0, zx1 = 24, int(w * 0.58)
    zy0 = int(max(0, qy0 - 48))
    zy1 = int(min(h, qy1 + 420))
    meta["region"] = [zx0, zy0, zx1, zy1]
    if zx1 - zx0 < 60 or zy1 - zy0 < 60:
        meta["reject"] = "side_zone_narrow"
        return None
    roi = gray[zy0:zy1, zx0:zx1]
    mask = roi < 210
    zh, zw = mask.shape
    for b in blocks:
        t = (b.get("text") or "").strip()
        if not t:
            continue
        if not (_is_body_line(t) or _is_option_line(t) or NEXT_Q_RE.match(t)):
            continue
        bx0, by0, bx1, by1 = (
            float(b["x0"]),
            float(b["y0"]),
            float(b["x1"]),
            float(b["y1"]),
        )
        if bx1 <= zx0 or bx0 >= zx1 or by1 <= zy0 or by0 >= zy1:
            continue
        rx0 = int(max(0, bx0 - zx0 - 2))
        rx1 = int(min(zw, bx1 - zx0 + 3))
        ry0 = int(max(0, by0 - zy0 - 2))
        ry1 = int(min(zh, by1 - zy0 + 3))
        mask[ry0:ry1, rx0:rx1] = False
    mask = _dilate(mask, 2)
    row_ink = mask.mean(axis=1)
    rows = np.where(row_ink > 0.01)[0]
    if len(rows) == 0:
        meta["reject"] = "side_no_ink"
        return None
    clusters: list[list[int]] = []
    start = prev = int(rows[0])
    for r in rows[1:]:
        r = int(r)
        if r - prev > 20:
            clusters.append([start, prev])
            start = r
        prev = r
    clusters.append([start, prev])
    anchor = qy0 - zy0
    cands = [c for c in clusters if c[1] - c[0] >= 30 and c[1] >= anchor + 40]
    if not cands:
        meta["reject"] = "side_no_cluster"
        return None
    cands.sort(key=lambda c: abs(c[0] - anchor))
    ry0, ry1 = cands[0]
    sub = mask[max(0, ry0 - 3) : ry1 + 4, :]
    col_ink = sub.mean(axis=0)
    cols = np.where(col_ink > 0.005)[0]
    if len(cols) == 0:
        meta["reject"] = "side_no_ink"
        return None
    cx0, cx1 = int(cols[0]), int(cols[-1]) + 1
    box = (
        max(0, zx0 + cx0 - 10),
        max(0, zy0 + ry0 - 10),
        min(w, zx0 + cx1 + 10),
        min(h, zy0 + ry1 + 10),
    )
    if box[2] - box[0] < 60 or box[3] - box[1] < 50:
        meta["reject"] = "side_too_small"
        return None
    meta["cluster_rows"] = [int(zy0 + ry0), int(zy0 + ry1)]
    return box


def compute_fig_box(
    gray: np.ndarray,
    blocks: list[dict],
    q_bbox: list[float] | None,
    content: str,
    y_bound: float | None = None,
) -> tuple[tuple[int, int, int, int] | None, dict]:
    h, w = gray.shape
    stem, opts, labels, others = classify_blocks(blocks, q_bbox, h, y_bound)
    meta: dict = {
        "n_stem": len(stem),
        "n_opt": len(opts),
        "n_label": len(labels),
        "mode": "below",
    }

    qy0 = float(q_bbox[1]) if q_bbox else 0
    qy1 = float(q_bbox[3]) if q_bbox else h
    qx0 = float(q_bbox[0]) if q_bbox else 40
    qx1 = float(q_bbox[2]) if q_bbox else w - 40

    stem_bottom = max((float(b["y1"]) for b in stem), default=qy0 + 40)
    bound_ys = [float(b["y0"]) for b in opts]
    for b in others:
        t = (b.get("text") or "").strip()
        if NEXT_Q_RE.match(t) and float(b["y0"]) > stem_bottom + 20:
            bound_ys.append(float(b["y0"]))
    for b in blocks:
        t = (b.get("text") or "").strip()
        by0 = float(b["y0"])
        if by0 <= stem_bottom + 15:
            continue
        if NEXT_Q_RE.match(t) or _is_option_line(t):
            bound_ys.append(by0)

    if bound_ys:
        opt_top = min(bound_ys)
    else:
        opt_top = min(h - 10, max(qy1, stem_bottom + 180))

    opt_bottom = max(
        (float(b["y1"]) for b in opts if float(b["y0"]) <= stem_bottom + 25),
        default=None,
    )
    next_q_top = min(
        (
            float(b["y0"])
            for b in blocks
            if NEXT_Q_RE.match((b.get("text") or "").strip())
            and float(b["y0"]) > (opt_bottom or stem_bottom) + 20
        ),
        default=None,
    )
    # 选项紧跟题干（无间隙）→ 图在选项之下
    fig_after_options = (
        opt_bottom is not None
        and opt_top <= stem_bottom + 25
        and opt_bottom > stem_bottom + 10
    )
    if not fig_after_options:
        if opt_top > stem_bottom + 420:
            opt_top = stem_bottom + 420
        if opt_top <= stem_bottom + 25:
            opt_top = min(h - 10, stem_bottom + 160)

    content = content or ""
    max_h = 380
    if any(m in content for m in RIGHT_MARK):
        meta["mode"] = "right"
        box = _side_figure_box(
            gray, blocks, (qx0, qy0, qx1, qy1), stem + opts, "right", meta
        )
        return box, meta
    if any(m in content for m in LEFT_MARK):
        meta["mode"] = "left"
        box = _side_figure_box(
            gray, blocks, (qx0, qy0, qx1, qy1), stem + opts, "left", meta
        )
        return box, meta
    if fig_after_options:
        meta["mode"] = "below_options"
        y0 = int(opt_bottom - 4)
        lower = next_q_top if next_q_top is not None else min(h - 8, y0 + max_h)
        y1 = int(min(h - 8, lower + 4, y0 + max_h))
    else:
        meta["mode"] = "below"
        # 区域要紧：y0 吃进题干底会把题干行带进墨迹，y1 吃进选项顶同理
        # （net:43:X25 波形图被题干+选项包围，+12/-8 的余量把它们全抓了）
        y0 = int(stem_bottom + 2)
        y1 = int(min(h - 8, opt_top - 4, y0 + max_h))
        if y1 - y0 < 36:
            y0 = int(max(qy0, stem_bottom - 30))
            y1 = int(min(h - 8, y0 + 200, opt_top + 20))
    region = (28, y0, w - 28, y1)

    meta["region"] = list(region)
    meta["stem_bottom"] = stem_bottom
    meta["opt_top"] = opt_top

    box = ink_bbox(gray, region, max_h=max_h)
    if box is None or (box[3] - box[1] < 50):
        meta["fallback"] = "wide_band"
        # 从 region 外扩（而不是重算题干/选项锚点）：below_options 等模式下
        # 锚点语义不同，重算会把区域截到文本带里
        y0 = int(max(0, region[1] - 10))
        y1 = int(min(h - 8, y0 + max_h, region[3] + 20))
        wide = (20, y0, w - 20, y1)
        box2 = ink_bbox(
            gray, wide, thr=215, row_frac=0.004, col_frac=0.003, max_h=max_h, pad=12
        )
        if box2 and (box is None or (box2[3] - box2[1] > box[3] - box[1])):
            box = box2
            region = wide
            meta["region"] = list(region)

    if box is None:
        return None, meta

    near_labels = []
    rx0, ry0, rx1, ry1 = region
    for b in labels + [b for b in others if _is_labelish(b.get("text") or "")]:
        cy = 0.5 * (float(b["y0"]) + float(b["y1"]))
        cx = 0.5 * (float(b["x0"]) + float(b["x1"]))
        if ry0 - 30 <= cy <= ry1 + 30 and rx0 - 40 <= cx <= rx1 + 40:
            near_labels.append(b)
    box2 = expand_with_labels(box, near_labels, margin=32)
    x0, y0, x1, y1 = box2
    pad_reg = (max(0, x0 - 10), max(0, y0 - 10), min(w, x1 + 10), min(h, y1 + 10))
    tight = ink_bbox(gray, pad_reg, thr=210, pad=10, max_h=max_h + 40)
    if tight:
        tx0, ty0, tx1, ty1 = tight
        u = union_boxes([tight, box2]) or tight
        ux0, uy0, ux1, uy1 = u
        box = (
            max(tx0 - 36, ux0),
            max(ty0 - 36, uy0),
            min(tx1 + 36, ux1),
            min(ty1 + 36, uy1),
        )
    else:
        box = box2

    if box[3] - box[1] > max_h + 60:
        box = (box[0], box[1], box[2], box[1] + max_h + 60)

    # 最终框收敛回候选区（±14 容差）：标签扩展与墨迹并集不得侵入邻题领土
    box = (
        max(region[0] - 14, box[0]),
        max(region[1] - 14, box[1]),
        min(region[2] + 14, box[2]),
        min(region[3] + 14, box[3]),
    )

    if box[2] - box[0] < 40 or box[3] - box[1] < 36:
        meta["reject"] = "too_small"
        return None, meta

    area = (box[2] - box[0]) * (box[3] - box[1])
    if area > 0.45 * w * h:
        meta["reject"] = "too_large"
        return None, meta

    meta["box"] = list(box)
    return box, meta


def trim_expand(img: Image.Image, pad=4, border=12) -> Image.Image:
    g = np.array(img.convert("L"))
    m = g < 248
    if m.any():
        ys, xs = np.where(m)
        img = img.crop(
            (
                max(0, int(xs.min()) - pad),
                max(0, int(ys.min()) - pad),
                min(img.size[0], int(xs.max()) + pad + 1),
                min(img.size[1], int(ys.max()) + pad + 1),
            )
        )
    return ImageOps.expand(img, border, "white")


def ensure_img_line(exp: str, rel: str) -> str:
    line = f"题目图片：{rel}"
    exp = (exp or "").rstrip()
    lines = [
        ln
        for ln in exp.splitlines()
        if not ln.strip().startswith("题目图片") and not ln.strip().startswith("题图")
    ]
    body = "\n".join(lines).rstrip()
    return (body + "\n" + line + "\n") if body else (line + "\n")


def write_course(course: str, data: dict) -> None:
    cname, stem = COURSE_META[course]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (BANK / f"{stem}.json").write_text(payload, encoding="utf-8")
    (BANK / f"{stem}.js").write_text(
        f"// auto-generated from {stem}.json\n"
        "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
        f'window.__COURSE_CACHE__["{cname}"] = ' + payload + ";\n",
        encoding="utf-8",
    )
    gz = BANK / f"{stem}.json.gz"
    if gz.exists():
        with gzip.open(gz, "wt", encoding="utf-8") as f:
            f.write(payload)


def collect_targets(course_filter: str | None, only: set[str] | None):
    items = []
    # 人工校准框（可选）：{ "course:page:id": [x0,y0,x1,y1] }，优先生效
    manual_boxes: dict = {}
    mpath = ROOT / "data" / "fig_manual_boxes.json"
    if mpath.exists():
        try:
            manual_boxes = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            manual_boxes = {}
    # 同页所有题的 bbox 索引（含无图题），供邻题边界检查使用
    page_boxes: dict[tuple[str, int], list[tuple[float, float]]] = {}
    for code, (cname, stem) in COURSE_META.items():
        if course_filter and code != course_filter:
            continue
        path = BANK / f"{stem}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for ch in data.get("chapters", []):
            ch_name = ch.get("name") or ""
            for q in ch.get("questions", []):
                pg, bb = q.get("page"), q.get("bbox")
                if pg is not None and bb and len(bb) == 4:
                    page_boxes.setdefault((code, int(pg)), []).append(
                        (float(bb[1]), float(bb[3]))
                    )
                ok, cropped = looks_fig(q)
                key = f"{code}:{q.get('page')}:{q.get('id')}"
                manual = manual_boxes.get(key)
                # 人工框显式声明该题有图（题干可无"如下图"类标记，如 X23）
                if not ok and manual and not (
                    isinstance(manual, dict) and manual.get("drop")
                ):
                    ok, cropped = True, cropped
                if not ok:
                    continue
                if only and key not in only and f"{key}:{ch_name}" not in only:
                    # also allow course:page:id match
                    if key not in only:
                        continue
                items.append(
                    {
                        "course": code,
                        "course_name": cname,
                        "stem_file": stem,
                        "chapter": ch_name,
                        "q": q,
                        "key": key,
                        "old_cropped": cropped,
                        "manual_box": manual_boxes.get(key),
                    }
                )
    for it in items:
        pg = it["q"].get("page")
        it["page_boxes"] = (
            page_boxes.get((it["course"], int(pg))) if pg is not None else []
        ) or []
    return items


def process_one(item: dict, page_cache: dict, ocr_cache: dict, dry: bool) -> dict:
    q = item["q"]
    code = item["course"]
    page = q.get("page")
    qid = q.get("id")
    content = q.get("content") or ""
    bbox = q.get("bbox")

    rec = {
        "key": item["key"],
        "course": code,
        "page": page,
        "id": qid,
        "chapter": item["chapter"],
        "ok": False,
    }
    if page is None:
        rec["error"] = "no page"
        return rec

    page_i = int(page)
    pdf = PDF_ROOT / code / f"page_{page_i:03d}.png"
    if not pdf.exists():
        rec["error"] = f"missing pdf {pdf.name}"
        return rec

    ck = (code, page_i)
    if ck not in page_cache:
        im = Image.open(pdf).convert("RGB")
        page_cache[ck] = im
        ocr_cache[ck] = load_ocr(code, page_i)
    page_img = page_cache[ck]
    blocks = ocr_cache[ck]
    gray = np.array(page_img.convert("L"))

    manual = item.get("manual_box")
    if isinstance(manual, dict) and manual.get("drop"):
        # 人工确认：该题实际无图（"图"在答案区），摘除配图标记
        rec["ok"] = True
        rec["dropped"] = True
        if not dry:
            q["has_image"] = False
            q["image_ref"] = None
            ans = q.get("answer")
            if isinstance(ans, dict):
                lines = [
                    ln
                    for ln in (ans.get("explanation") or "").splitlines()
                    if not ln.strip().startswith(("题目图片", "题图"))
                ]
                ans["explanation"] = "\n".join(lines).rstrip() + (
                    "\n" if lines else ""
                )
        return rec
    manual_box = None
    manual_page = page_i
    if isinstance(manual, dict):
        manual_page = int(manual.get("page") or page_i)
        manual_box = manual.get("box")
    elif isinstance(manual, (list, tuple)) and len(manual) == 4:
        manual_box = manual
    source_page = page_i
    if manual_box:
        # 人工校准框：跳过自动检测，直接采用（重建后依然生效）。
        # 支持 box 在另一页（解答题的图常在下一页顶部）。
        if manual_page != page_i:
            mpdf = PDF_ROOT / code / f"page_{manual_page:03d}.png"
            if not mpdf.exists():
                rec["error"] = f"missing pdf {mpdf.name}"
                return rec
            mk = (code, manual_page)
            if mk not in page_cache:
                page_cache[mk] = Image.open(mpdf).convert("RGB")
                ocr_cache[mk] = load_ocr(code, manual_page)
            page_img = page_cache[mk]
            blocks = ocr_cache[mk]
            gray = np.array(page_img.convert("L"))
            source_page = manual_page
        safe_bbox, continues_next_page = None, False
        box = tuple(int(v) for v in manual_box)
        meta = {"mode": "manual", "region": list(box)}
    else:
        safe_bbox, continues_next_page = question_ocr_bbox(
            str(qid or ""), bbox, blocks, page_img.width, page_img.height
        )
        box, meta = None, {}

    if continues_next_page:
        next_page = page_i + 1
        next_pdf = PDF_ROOT / code / f"page_{next_page:03d}.png"
        if next_pdf.exists():
            next_ck = (code, next_page)
            if next_ck not in page_cache:
                page_cache[next_ck] = Image.open(next_pdf).convert("RGB")
                ocr_cache[next_ck] = load_ocr(code, next_page)
            next_img = page_cache[next_ck]
            next_blocks = ocr_cache[next_ck]
            next_gray = np.array(next_img.convert("L"))
            box, meta = carryover_top_figure_box(next_gray, next_blocks)
            if box:
                page_img = next_img
                blocks = next_blocks
                gray = next_gray
                source_page = next_page
                safe_bbox = None
            else:
                box = None
        else:
            box, meta = None, {"mode": "cross_page", "reject": "missing_next_page"}

    # A figure crop must stay inside the current question.  The previous
    # implementation could drift below q_bbox and silently capture the next
    # exercise.  When confidence is low, a full-current-question crop is less
    # elegant but always usable and never shows an unrelated question.
    def _validate(cbox, cmeta):
        """返回 (box, meta, reject_reason)；box 为 None 表示候选被拒。"""
        if not cbox:
            return None, cmeta, cmeta.get("reject") or "detector_failed"
        mode = cmeta.get("mode")
        if mode == "marker_band":
            cov = ocr_box_coverage(cbox, blocks)
            cmeta["ocr_coverage"] = round(cov, 4)
            if overlaps_option_text(cbox, blocks):
                return None, cmeta, "candidate_is_option_text"
            if cbox[2] - cbox[0] < 160 or cbox[3] - cbox[1] < 40:
                return None, cmeta, "candidate_too_small"
            if cov > 0.32:
                return None, cmeta, "ocr_text_dominates_crop"
        if mode not in ("cross_page", "right", "left"):
            # 邻题边界：候选框不得越出同页相邻题的领土。右图/左图可与邻题
            # 文字同高并列，由 _side_figure_box 的聚簇逻辑自约束，不适用此查。
            cmeta["neighbor_y"] = [round(nb_lo), round(nb_hi)]
            if cbox[1] < nb_lo - 20 or cbox[3] > nb_hi + 20:
                return None, cmeta, "outside_question_bbox"
        return cbox, cmeta, None

    h, w = gray.shape
    nb_lo, nb_hi = _neighbor_y_bounds(item.get("page_boxes") or [], bbox, h)
    fallback_reason = None
    if not box:
        box, meta = marker_band_box(gray, blocks, safe_bbox, content)
        box, meta, fallback_reason = _validate(box, meta)
        if not box:
            # marker 候选被拒，再试通用检测；两边都不行才回退整题裁
            box2, meta2 = compute_fig_box(
                gray, blocks, safe_bbox, content, y_bound=nb_hi
            )
            box2, meta2, reason2 = _validate(box2, meta2)
            if box2:
                box, meta, fallback_reason = box2, meta2, None
            else:
                meta = dict(meta2)
                meta["marker_reject"] = fallback_reason
                meta["compute_reject"] = reason2
                fallback_reason = fallback_reason or reason2

    if not box:
        safe = question_fallback_box(safe_bbox, page_img.width, page_img.height)
        if safe:
            box = safe
            prev_meta = meta
            meta = {
                "mode": "question_fallback",
                "fallback": fallback_reason
                or prev_meta.get("reject")
                or "detector_failed",
                "region": list(safe),
            }
            for k in ("marker_reject", "compute_reject", "neighbor_y"):
                if prev_meta.get(k) is not None:
                    meta[k] = prev_meta[k]
    rec["meta"] = {k: v for k, v in meta.items() if k != "box"}
    if not box:
        rec["error"] = meta.get("reject") or "no_ink"
        return rec

    x0, y0, x1, y1 = box
    rec["box"] = [x0, y0, x1, y1]
    rec["size"] = [x1 - x0, y1 - y0]

    # 图内文字碎片剥离：仅精确定位模式（保底整题裁不动 content，防误删）。
    # dry-run 只记录不写回，清单进 report 供人工核对。
    if meta.get("mode") != "question_fallback":
        strip_region = meta.get("region") or [x0, y0, x1, y1]
        new_content, stripped = strip_fig_fragments(
            q.get("content") or "", strip_region, blocks
        )
        if stripped:
            rec["stripped"] = stripped
            if not dry:
                q["content"] = new_content

    rel = item["old_cropped"] or f"crops/{code}/page_{page_i:03d}_{qid}.png"
    if not rel.startswith("crops/"):
        rel = f"crops/{code}/{Path(rel).name}"
    rec["image"] = rel

    if dry:
        rec["ok"] = True
        rec["dry"] = True
        return rec

    crop = trim_expand(page_img.crop((x0, y0, x1, y1)))
    out = BANK / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, "PNG")
    rec["bytes"] = out.stat().st_size
    rec["out_size"] = list(crop.size)

    q["has_image"] = True
    note = (
        "人工校准裁图"
        if meta.get("mode") == "manual"
        else "题目配图，按含图提示语自动定位"
        if meta.get("mode") == "marker_band"
        else "题目区域保底裁图（避免错截到其他题）"
        if meta.get("mode") == "question_fallback"
        else "题干含图，OCR空隙+墨迹自动重裁"
    )
    q["image_ref"] = {
        "page": source_page,
        "note": note,
        "cropped": rel,
        "box": [x0, y0, x1, y1],
    }
    ans = q.get("answer")
    if isinstance(ans, dict):
        ans["explanation"] = ensure_img_line(ans.get("explanation") or "", rel)
    rec["ok"] = True
    return rec


def main():
    ap = argparse.ArgumentParser(description="Auto re-crop 408 figure questions")
    ap.add_argument("--course", choices=list(COURSE_META), default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", action="append", default=[], help="course:page:id")
    ap.add_argument(
        "--report",
        default=str(REPO_TEMP / "fig-recrop-report.json"),
    )
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    only = set(args.only) if args.only else None
    items = collect_targets(args.course, only)
    if args.limit:
        items = items[: args.limit]
    print(f"targets: {len(items)} dry={args.dry_run}")

    page_cache: dict = {}
    ocr_cache: dict = {}
    results = []
    by_course_data: dict[str, dict] = {}

    # load json once per course
    loaded = {}
    for it in items:
        code = it["course"]
        if code not in loaded:
            stem = COURSE_META[code][1]
            loaded[code] = json.loads(
                (BANK / f"{stem}.json").read_text(encoding="utf-8")
            )
        # re-bind q to live object in loaded data
        live = None
        for ch in loaded[code]["chapters"]:
            if (ch.get("name") or "") != it["chapter"]:
                continue
            for q in ch.get("questions", []):
                if q.get("id") == it["q"].get("id") and q.get("page") == it["q"].get(
                    "page"
                ):
                    live = q
                    break
            if live:
                break
        if live is None:
            # fallback search
            for ch in loaded[code]["chapters"]:
                for q in ch.get("questions", []):
                    if q.get("id") == it["q"].get("id") and int(
                        q.get("page") or -1
                    ) == int(it["q"].get("page") or -2):
                        live = q
                        break
                if live:
                    break
        if live is None:
            results.append(
                {**{"key": it["key"], "ok": False, "error": "q not found in json"}}
            )
            continue
        it["q"] = live
        r = process_one(it, page_cache, ocr_cache, args.dry_run)
        results.append(r)
        status = "OK" if r.get("ok") else "FAIL"
        print(
            f"  [{status}] {it['key']} "
            f"{r.get('size') or r.get('error')} "
            f"mode={r.get('meta', {}).get('mode')}"
        )

    ok_n = sum(1 for r in results if r.get("ok"))
    fail_n = len(results) - ok_n
    print(f"done ok={ok_n} fail={fail_n}")

    if not args.dry_run:
        for code, data in loaded.items():
            write_course(code, data)
            print(f"  wrote data-{code}")
        # refresh fig-review-data if present
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from serve_fig_review import collect_items  # type: ignore

            snap = collect_items()
            (Path(__file__).resolve().parents[1] / "output" / "qa" / "fig-review-data.json").write_text(
                json.dumps(
                    {"generated": True, "count": len(snap), "items": snap},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print("  refreshed fig-review-data.json")
        except Exception as e:
            print("  skip fig-review-data:", e)

    report = {
        "ok": ok_n,
        "fail": fail_n,
        "dry_run": args.dry_run,
        "results": results,
    }
    rep_path = Path(args.report)
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("report:", rep_path)

    # fail summary
    fails = [r for r in results if not r.get("ok")]
    if fails:
        print("FAILS:")
        for r in fails[:30]:
            print(" ", r.get("key"), r.get("error"), r.get("meta", {}).get("mode"))


if __name__ == "__main__":
    main()
