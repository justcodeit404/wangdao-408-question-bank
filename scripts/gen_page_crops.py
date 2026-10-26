#!/usr/bin/env python3
"""给 hold 选择题生成原页兜底裁图，供 viewer 的 pageFallbackHtml 直接显示。

hold 题不再隐藏，但它们没通过原书复核，题干/答案只能以原书为准。按台账里每题的
page + bbox，从 assets/pdf_images/<course>/page_NNN.png 裁一条整宽区域到
math-bank/page_crops/<course>/ —— 单独一个目录，不混进 crops/（那里是真正的题图，
混进去会被 detect_image_ref 当成配图）。只处理选择题：408 壳是 choice-only，
解答题的裁图没有任何地方会渲染。已存在的文件默认不重裁。

用法（在 apps/bank-408）：
  python scripts/gen_page_crops.py                # 全部科目，只补缺失
  python scripts/gen_page_crops.py --course net   # 只补一科
  python scripts/gen_page_crops.py --force        # 全部重裁
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import COURSES, MATH_BANK_DIR  # noqa: E402

LEDGER_PATH = Path(__file__).resolve().parents[1] / "data" / "quality" / "quality-ledger.json"
PADDING = 24


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _published(bank_dir: Path, course_key: str) -> dict[tuple[str, str], dict]:
    path = bank_dir / f"data-{course_key}.json"
    if not path.is_file():
        return {}
    index: dict[tuple[str, str], dict] = {}
    for chapter in _load(path).get("chapters") or []:
        for question in chapter.get("questions") or []:
            index[(chapter.get("name") or "", question.get("id") or "")] = question
    return index


def crop_page_band(page_path: Path, bbox: list, out_path: Path) -> bool:
    """按 bbox 裁整宽横条（左右留边、上下补 padding），写 PNG。"""
    try:
        image = Image.open(page_path)
    except OSError as exc:
        print(f"[page-crops] open failed {page_path}: {exc}")
        return False
    width, height = image.size
    try:
        _, y0, _, y1 = [float(v) for v in bbox[:4]]
    except (TypeError, ValueError):
        return False
    top = max(0, int(y0) - PADDING)
    bottom = min(height, int(y1) + PADDING)
    if bottom - top < 10:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # JPEG q88：整宽横条存 PNG 平均 200KB，428 道就是 90MB 资产；JPEG 约 1/5 且文字仍清晰。
    image.crop((PADDING // 2, top, width - PADDING // 2, bottom)).save(
        out_path, "JPEG", quality=88, optimize=True
    )
    return True


def generate(
    *,
    ledger_path: Path = LEDGER_PATH,
    bank_dir: Path = MATH_BANK_DIR,
    images_dir_for: Callable[[str], Path] | None = None,
    courses: list[str] | None = None,
    force: bool = False,
) -> dict[str, int]:
    if images_dir_for is None:
        by_key = {c.key: c for c in COURSES}
        images_dir_for = lambda key: by_key[key].pdf_images_dir  # noqa: E731
    ledger = _load(ledger_path)
    held = [item for item in (ledger.get("items") or {}).values()
            if item.get("overall") == "hold"]
    if courses:
        held = [item for item in held if item.get("course_key") in courses]
    counts = {"total": len(held), "written": 0, "existing": 0, "missing": 0}
    by_course: dict[str, list[dict]] = {}
    for item in held:
        by_course.setdefault(str(item.get("course_key")), []).append(item)
    for course_key, items in sorted(by_course.items()):
        published = _published(bank_dir, course_key)
        page_dir = images_dir_for(course_key)
        for item in items:
            question = published.get((str(item.get("chapter")), str(item.get("question_id"))))
            page = (question or {}).get("page")
            bbox = (question or {}).get("bbox")
            # 408 壳是 choice-only（choice-only.js 在数据层滤掉解答题）：给解答题裁图没人看，
            # 428 道全裁要 38MB 资产。只给壳真的会渲染的 hold 选择题裁。
            if not question or not page or not bbox or question.get("type") != "选择题":
                counts["missing"] += 1
                continue
            out_path = (bank_dir / "page_crops" / course_key
                        / f"page_{int(page):03d}_{question['id']}.jpg")
            if out_path.exists() and not force:
                counts["existing"] += 1
                continue
            if crop_page_band(page_dir / f"page_{int(page):03d}.png", bbox, out_path):
                counts["written"] += 1
            else:
                counts["missing"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course", action="append", default=[],
                        choices=[c.key for c in COURSES], help="只处理这一科（可重复）")
    parser.add_argument("--force", action="store_true", help="已有裁图也重裁")
    args = parser.parse_args()
    counts = generate(courses=args.course or None, force=args.force)
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
