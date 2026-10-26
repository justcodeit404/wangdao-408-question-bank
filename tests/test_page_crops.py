"""hold 选择题的原页兜底裁图：只裁会被壳渲染的 hold 选择题，落到独立目录，已有文件不重裁。"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from gen_page_crops import generate


def _page_png(path: Path, size: tuple[int, int] = (400, 600)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, "PNG")


def _fixture(tmp: Path) -> dict:
    ledger = {
        "items": {
            "408:cs408-net::概况 · 选择题::X01": {
                "overall": "hold",
                "course_key": "net",
                "chapter": "概况 · 选择题",
                "question_id": "X01",
            },
            "408:cs408-net::概况 · 选择题::X02": {
                "overall": "certified",
                "course_key": "net",
                "chapter": "概况 · 选择题",
                "question_id": "X02",
            },
            # 解答题 hold：408 壳是 choice-only，不该浪费资产给它裁图
            "408:cs408-net::概况 · 解答题::A01": {
                "overall": "hold",
                "course_key": "net",
                "chapter": "概况 · 解答题",
                "question_id": "A01",
            },
        }
    }
    bank = {
        "chapters": [
            {
                "name": "概况 · 选择题",
                "questions": [
                    {"id": "X01", "type": "选择题", "page": 7, "bbox": [40, 200, 360, 260]},
                    {"id": "X02", "type": "选择题", "page": 7, "bbox": [40, 300, 360, 360]},
                ],
            },
            {
                "name": "概况 · 解答题",
                "questions": [
                    {"id": "A01", "type": "解答题", "page": 7, "bbox": [40, 400, 360, 460]},
                ],
            },
        ]
    }
    ledger_path = tmp / "ledger.json"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    bank_dir = tmp / "math-bank"
    bank_dir.mkdir()
    (bank_dir / "data-net.json").write_text(json.dumps(bank, ensure_ascii=False), encoding="utf-8")
    images = tmp / "images"
    _page_png(images / "page_007.png")
    return {"ledger": ledger_path, "bank": bank_dir, "images": images}


def test_only_hold_choice_questions_get_page_crops(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    counts = generate(
        ledger_path=paths["ledger"],
        bank_dir=paths["bank"],
        images_dir_for=lambda key: paths["images"],
    )
    crops = paths["bank"] / "page_crops" / "net"
    out = crops / "page_007_X01.jpg"
    assert counts == {"total": 2, "written": 1, "existing": 0, "missing": 1}
    assert out.is_file()
    # 只裁 bbox 那一横条（含 padding），整宽
    with Image.open(out) as crop:
        assert crop.width > 300
        assert crop.height < 150
    assert not (crops / "page_007_X02.jpg").exists()  # certified
    assert not (crops / "page_007_A01.jpg").exists()  # 解答题


def test_existing_crop_is_not_rebuilt(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    kw = {"ledger_path": paths["ledger"], "bank_dir": paths["bank"],
          "images_dir_for": lambda key: paths["images"]}
    generate(**kw)
    again = generate(**kw)
    assert again == {"total": 2, "written": 0, "existing": 1, "missing": 1}
