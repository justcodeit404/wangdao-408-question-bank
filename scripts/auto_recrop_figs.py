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
  math-bank/fig-review-data.json（若存在审查页数据）
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

OPT_RE = re.compile(r"^[A-Da-dＡ-Ｄ][\s\.．、\)）]|^[A-D]\s*$|^[A-D]\.\s*\S")
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
        if _is_body_line(text) or _is_option_line(text) or NEXT_Q_RE.match(text):
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
    m = re.search(r"(\d+)$", str(qid or ""))
    if not m or not str(qid).upper().startswith("X"):
        return q_bbox, False
    number = int(m.group(1))
    cur_re = re.compile(rf"^0*{number}\s*[\.．、]")
    next_re = re.compile(rf"^0*{number + 1}\s*[\.．、]")
    ordered = sorted(blocks, key=lambda b: (float(b["y0"]), float(b["x0"])))
    starts = [b for b in ordered if cur_re.match((b.get("text") or "").strip())]
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


def classify_blocks(blocks: list[dict], q_bbox: list[float] | None, page_h: int):
    if q_bbox and len(q_bbox) == 4:
        qx0, qy0, qx1, qy1 = [float(v) for v in q_bbox]
        y0 = max(0, qy0 - 30)
        y1 = min(page_h, qy1 + 80)
    else:
        y0, y1 = 0, page_h

    stem, opts, labels, others = [], [], [], []
    q_top = float(q_bbox[1]) if q_bbox and len(q_bbox) == 4 else 0.0
    for b in blocks:
        by0, by1 = float(b["y0"]), float(b["y1"])
        if by1 < y0 or by0 > y1:
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


def compute_fig_box(
    gray: np.ndarray,
    blocks: list[dict],
    q_bbox: list[float] | None,
    content: str,
) -> tuple[tuple[int, int, int, int] | None, dict]:
    h, w = gray.shape
    stem, opts, labels, others = classify_blocks(blocks, q_bbox, h)
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

    if opt_top > stem_bottom + 420:
        opt_top = stem_bottom + 420
    if opt_top <= stem_bottom + 25:
        opt_top = min(h - 10, stem_bottom + 160)

    content = content or ""
    max_h = 380
    if any(m in content for m in RIGHT_MARK):
        meta["mode"] = "right"
        rx0 = int(max(qx0, min(w * 0.42, qx1 - 20)))
        y0 = int(max(0, min(qy0, stem_bottom) - 10))
        y1 = int(min(h, min(opt_top + 10, y0 + max_h)))
        region = (rx0, y0, w - 24, y1)
    elif any(m in content for m in LEFT_MARK):
        meta["mode"] = "left"
        rx1 = int(min(qx1, max(w * 0.55, qx0 + 20)))
        y0 = int(max(0, min(qy0, stem_bottom) - 10))
        y1 = int(min(h, min(opt_top + 10, y0 + max_h)))
        region = (24, y0, rx1, y1)
    else:
        meta["mode"] = "below"
        y0 = int(stem_bottom - 8)
        y1 = int(min(h - 8, opt_top + 12, y0 + max_h))
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
        y0 = int(max(0, stem_bottom - 15))
        y1 = int(min(h - 8, y0 + max_h, opt_top + 40))
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
                ok, cropped = looks_fig(q)
                if not ok:
                    continue
                key = f"{code}:{q.get('page')}:{q.get('id')}"
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
                    }
                )
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

    safe_bbox, continues_next_page = question_ocr_bbox(
        str(qid or ""), bbox, blocks, page_img.width, page_img.height
    )
    source_page = page_i

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
    else:
        box, meta = None, {}

    if not box:
        box, meta = marker_band_box(gray, blocks, safe_bbox, content)
    if not box:
        box, meta = compute_fig_box(gray, blocks, safe_bbox, content)

    # A figure crop must stay inside the current question.  The previous
    # implementation could drift below q_bbox and silently capture the next
    # exercise.  When confidence is low, a full-current-question crop is less
    # elegant but always usable and never shows an unrelated question.
    fallback_reason = None
    if box and meta.get("mode") == "marker_band":
        text_coverage = ocr_box_coverage(box, blocks)
        meta["ocr_coverage"] = round(text_coverage, 4)
        if overlaps_option_text(box, blocks):
            fallback_reason = "candidate_is_option_text"
            box = None
        elif box[2] - box[0] < 160 or box[3] - box[1] < 40:
            fallback_reason = "candidate_too_small"
            box = None
        elif text_coverage > 0.32:
            fallback_reason = "ocr_text_dominates_crop"
            box = None
    if box and safe_bbox and len(safe_bbox) == 4 and meta.get("mode") != "cross_page":
        _, qy0, _, qy1 = [float(v) for v in safe_bbox]
        overlap_y = max(0.0, min(float(box[3]), qy1) - max(float(box[1]), qy0))
        box_h = max(1.0, float(box[3] - box[1]))
        if overlap_y / box_h < 0.9 or box[1] < qy0 - 25 or box[3] > qy1 + 25:
            fallback_reason = "outside_question_bbox"
            box = None

    if not box:
        safe = question_fallback_box(safe_bbox, page_img.width, page_img.height)
        if safe:
            box = safe
            meta = {
                "mode": "question_fallback",
                "fallback": fallback_reason or meta.get("reject") or "detector_failed",
                "region": list(safe),
            }
    rec["meta"] = {k: v for k, v in meta.items() if k != "box"}
    if not box:
        rec["error"] = meta.get("reject") or "no_ink"
        return rec

    x0, y0, x1, y1 = box
    rec["box"] = [x0, y0, x1, y1]
    rec["size"] = [x1 - x0, y1 - y0]

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
        "题目配图，按含图提示语自动定位"
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
            (BANK / "fig-review-data.json").write_text(
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
