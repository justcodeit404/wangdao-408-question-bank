#!/usr/bin/env python3
"""把 PDF 指定页渲染为 page_NNN.png，供 OCR / 裁图使用。

用法：
  python scripts/render_pdf_pages.py --course net
  python scripts/render_pdf_pages.py --course net --pages 14-50
  python scripts/render_pdf_pages.py --course net --all-pages
  python scripts/render_pdf_pages.py --pdf path.pdf --out-dir assets/pdf_images/net --from-qa data/qa/net_qa_pairs.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz

from config import COURSE_BY_KEY, COURSES

sys.stdout.reconfigure(encoding="utf-8")


def pages_from_qa(qa_json: Path) -> set[int]:
    data = json.loads(qa_json.read_text(encoding="utf-8"))
    total = int(data.get("total_pages") or 0)
    pairs = data.get("qa_pairs") or []
    pages: set[int] = set()
    for i, q in enumerate(pairs):
        q_start = int(q["q_start"])
        if i + 1 < len(pairs):
            end = int(pairs[i + 1]["q_start"]) - 1
        else:
            end = total
        for p in range(q_start, end + 1):
            if 1 <= p <= total:
                pages.add(p)
    return pages


def parse_page_spec(spec: str, total: int) -> set[int]:
    """解析 1,3,5-10 形式。"""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            for p in range(lo, hi + 1):
                if 1 <= p <= total:
                    out.add(p)
        else:
            p = int(part)
            if 1 <= p <= total:
                out.add(p)
    return out


def render_pages(
    pdf: Path,
    out_dir: Path,
    pages: set[int],
    zoom: float = 2.0,
    skip_existing: bool = True,
) -> tuple[int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    mat = fitz.Matrix(zoom, zoom)
    done = 0
    skipped = 0
    sorted_pages = sorted(pages)
    print(f"PDF: {pdf.name}  pages={doc.page_count}  render={len(sorted_pages)}  zoom={zoom}")
    for i, page_num in enumerate(sorted_pages):
        out = out_dir / f"page_{page_num:03d}.png"
        if skip_existing and out.exists() and out.stat().st_size > 1000:
            skipped += 1
            continue
        if page_num < 1 or page_num > doc.page_count:
            print(f"  [!] skip invalid page {page_num}")
            continue
        page = doc[page_num - 1]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(out))
        done += 1
        if (i + 1) % 20 == 0 or i + 1 == len(sorted_pages):
            print(f"  [{i + 1}/{len(sorted_pages)}] last=page_{page_num:03d}.png written={done} skipped={skipped}")
    doc.close()
    return done, skipped


def main():
    ap = argparse.ArgumentParser(description="Render PDF pages to PNG for OCR")
    ap.add_argument("--course", choices=[c.key for c in COURSES], help="课程 key: ds/coa/net/os")
    ap.add_argument("--pdf", type=Path, help="PDF 路径（不指定 course 时必填）")
    ap.add_argument("--out-dir", type=Path, help="输出目录")
    ap.add_argument("--from-qa", type=Path, help="从 qa_pairs 推导页码")
    ap.add_argument("--pages", type=str, help="页码范围，如 14-50,100")
    ap.add_argument("--all-pages", action="store_true", help="渲染全部页")
    ap.add_argument("--zoom", type=float, default=2.0, help="渲染倍率，默认 2.0（约 144dpi）")
    ap.add_argument("--force", action="store_true", help="覆盖已有 PNG")
    args = ap.parse_args()

    if args.course:
        c = COURSE_BY_KEY[args.course]
        pdf = c.pdf
        out_dir = args.out_dir or c.pdf_images_dir
        qa = args.from_qa or c.qa_json
        total = c.total_pages
    else:
        if not args.pdf or not args.out_dir:
            ap.error("未指定 --course 时需要 --pdf 与 --out-dir")
        pdf = args.pdf
        out_dir = args.out_dir
        qa = args.from_qa
        total = fitz.open(pdf).page_count

    if not pdf.exists():
        print(f"[!] PDF 不存在: {pdf}")
        sys.exit(1)

    if args.all_pages:
        pages = set(range(1, total + 1))
    elif args.pages:
        pages = parse_page_spec(args.pages, total)
    elif qa and Path(qa).exists():
        pages = pages_from_qa(Path(qa))
        print(f"从 QA 推导 {len(pages)} 页: {Path(qa).name}")
    else:
        ap.error("请指定 --pages / --all-pages / --from-qa")

    written, skipped = render_pages(
        pdf, out_dir, pages, zoom=args.zoom, skip_existing=not args.force
    )
    print(f"完成: written={written} skipped={skipped} out={out_dir}")


if __name__ == "__main__":
    main()
