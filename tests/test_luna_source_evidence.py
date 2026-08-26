import json
from pathlib import Path

import luna_source_evidence as luna


def _ocr_page(path: Path, choice: str = "B") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [
        {"text": "1.1.1 答案与解析", "x0": 0, "y0": 0, "x1": 100, "y1": 10},
        {"text": "一、单项选择题", "x0": 0, "y0": 20, "x1": 100, "y1": 30},
        {"text": f"01. {choice}", "x0": 0, "y0": 40, "x1": 100, "y1": 50},
    ]
    path.write_text(json.dumps({"page": 2, "backend": "CUDA", "blocks": blocks}, ensure_ascii=False), encoding="utf-8")


def _question_page(path: Path, *, option_b: str = "2") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [
        {"text": "01. 1+1=?", "x0": 0, "y0": 0, "x1": 100, "y1": 10},
        {"text": "A. 1", "x0": 0, "y0": 20, "x1": 50, "y1": 30},
        {"text": f"B. {option_b}", "x0": 60, "y0": 20, "x1": 110, "y1": 30},
        {"text": "C. 3", "x0": 0, "y0": 40, "x1": 50, "y1": 50},
        {"text": "D. 4", "x0": 60, "y0": 40, "x1": 110, "y1": 50},
    ]
    path.write_text(json.dumps({"page": 1, "backend": "CUDA", "blocks": blocks}, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path, *, image: bool = False, answer: str = "B") -> tuple[Path, Path]:
    root = tmp_path / "math-bank"
    root.mkdir()
    question = {
        "id": "X01",
        "type": "选择题",
        "content": "1+1=?",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "answer": {"choice": answer, "explanation": "加法"},
        "q_pages": [1],
        "a_pages": [2],
        "has_image": image,
    }
    data = {"chapters": [{"name": "第一章 · 小节 · 选择题", "questions": [question]}]}
    (root / "data-ds.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    # The fixture intentionally starts without a ledger item.  Include it only
    # to derive the stable UID/hash before writing the tracking record.
    seed_rows = luna.iter_questions(root, ["ds"], include_untracked=True)
    uid = seed_rows[0]["source_uid"]
    row = seed_rows[0]
    ledger = {
        "items": {
            uid: {
                "source_uid": uid,
                "source_hash": row["source_hash"],
                "source_fidelity": "pending",
                "answer_validation": "pending",
                "overall": "hold" if image else "pending",
                "reason_codes": ["existing_hold"] if image else [],
            }
        }
    }
    (root / "quality-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    raw = root / "data" / "ocr" / "ds" / "page_002.json"
    _ocr_page(raw, answer)
    _question_page(root / "data" / "ocr" / "ds" / "page_001.json")
    cache = tmp_path / "fresh-ocr" / "ds" / "page_002.json"
    _ocr_page(cache, answer)
    _question_page(cache.parent / "page_001.json")
    return root, cache.parent.parent


def test_low_risk_triads_produce_ingest_compatible_ocr_evidence(tmp_path):
    root, cache_root = _fixture(tmp_path)
    calls = []

    def runner(course, pages, *, force=False):
        calls.append((course.key, pages, force))
        return "CUDA"

    result = luna.generate_source_evidence(
        root=root,
        courses=["ds"],
        pass_id="source-p1",
        cache_root=cache_root,
        ocr_runner=runner,
    )
    item = result["packet"]["items"][0]
    # Fresh OCR must cover both answer pages (answer triad) and question pages
    # (stem/option evidence); answer-only OCR leaves every field unmatched.
    assert calls == [("ds", [1, 2], False)]
    assert item["method"] == "ocr"
    assert item["source_verified"] is True
    assert item["confidence"] >= 0.8
    assert item["published_choice"] == item["raw_ocr_choice"] == item["fresh_ocr_choice"] == "B"
    assert result["packet"]["packet_hash"] == luna.build_source_packet(
        result["packet"]["items"], pass_id="source-p1"
    )["packet_hash"]


def test_medium_or_high_risk_never_auto_passes(tmp_path):
    root, cache_root = _fixture(tmp_path, image=True)
    result = luna.generate_source_evidence(
        root=root,
        courses=["ds"],
        pass_id="source-p1",
        cache_root=cache_root,
        cache_only=True,
    )
    item = result["packet"]["items"][0]
    assert item["risk_tier"] in {"critical", "high", "medium"}
    assert item["method"] == "visual_pending"
    assert item["source_verified"] is False
    assert item["confidence"] == 0.0
    assert "risk_" in " ".join(item["reason_codes"])


def test_mismatched_fresh_cache_is_visual_pending(tmp_path):
    root, cache_root = _fixture(tmp_path, answer="B")
    _ocr_page(cache_root / "ds" / "page_002.json", "C")
    result = luna.generate_source_evidence(
        root=root, courses=["ds"], cache_root=cache_root, cache_only=True, pass_id="source-p1"
    )
    item = result["packet"]["items"][0]
    assert item["method"] == "visual_pending"
    assert item["source_verified"] is False
    assert "fresh_ocr_mismatch" in item["reason_codes"]


def test_question_stem_or_option_mismatch_is_visual_pending(tmp_path):
    root, cache_root = _fixture(tmp_path)
    _question_page(cache_root / "ds" / "page_001.json", option_b="different")
    result = luna.generate_source_evidence(
        root=root, courses=["ds"], cache_root=cache_root, cache_only=True, pass_id="source-p1"
    )
    item = result["packet"]["items"][0]
    assert item["method"] == "visual_pending"
    assert item["source_verified"] is False
    assert item["published_match"] is False
    assert "fresh_options_mismatch" in item["reason_codes"]


def test_dry_run_never_calls_runner_or_writes_output(tmp_path):
    root, cache_root = _fixture(tmp_path)
    output = tmp_path / "packet.json"

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not run OCR")

    result = luna.generate_source_evidence(
        root=root,
        courses=["ds"],
        cache_root=cache_root,
        output=output,
        dry_run=True,
        ocr_runner=forbidden,
    )
    assert result["summary"]["dry_run"] is True
    assert not output.exists()


def test_question_crop_stops_at_next_question_and_keeps_cross_page_window(tmp_path):
    ocr = tmp_path / "ocr"
    page = ocr / "page_001.json"
    page.parent.mkdir(parents=True)
    page.write_text(
        json.dumps(
            {
                "blocks": [
                    {"text": "01. 2+3=5", "x0": 0, "y0": 10},
                    {"text": "A. 1", "x0": 0, "y0": 20},
                    {"text": "B. 2", "x0": 0, "y0": 30},
                    {"text": "C. 3", "x0": 0, "y0": 40},
                    {"text": "D. 4", "x0": 0, "y0": 50},
                    {"text": "02. 2+3=6", "x0": 0, "y0": 60},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    crop = luna._question_crop(ocr, [1], "01")
    assert crop["anchor_found"] is True
    assert "2+3=5" in crop["text"]
    assert "2+3=6" not in crop["text"]


def test_numeric_and_operator_changes_never_pass_near_match():
    question = {
        "content": "计算 2+3=5。",
        "options": {"A": "正确", "B": "错误"},
    }
    changed_number = "01. 计算 2+4=5。 A. 正确 B. 错误"
    changed_operator = "01. 计算 2*3=5。 A. 正确 B. 错误"
    for text in (changed_number, changed_operator):
        fields = luna._field_matches(question, luna.normalize_source_text(text))
        assert fields["content"] is False
        assert fields["all_options"] is True


def test_option_letter_set_is_exact_not_satisfied_by_neighboring_labels():
    question = {"content": "选择正确项", "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}}
    text = luna.normalize_source_text("01.选择正确项 A.甲 B.乙 C.丙 E.丁")
    fields = luna._field_matches(question, text)
    assert fields["labels"] == ["A", "B", "C", "E"]
    assert fields["labels_match"] is False
    assert fields["all_options"] is False
