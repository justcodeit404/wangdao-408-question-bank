import json

from cross_validate_answers import (
    OCR_CACHE_PROTOCOL,
    PUBLISHED_DATA,
    answer_for_split_question,
    answer_number,
    classify_evidence,
    normalize_answer,
    ocr_cache_valid,
)


def test_quality_hold_hashes_published_viewer_data():
    assert PUBLISHED_DATA["ds"].name == "data-ds.json"
    assert PUBLISHED_DATA["coa"].name == "data-coa.json"
    assert PUBLISHED_DATA["net"].name == "data-net.json"
    assert PUBLISHED_DATA["os"].name == "data-os.json"


def test_answer_normalization_preserves_order_and_repetition():
    assert normalize_answer("B、E、C、D") == "BECD"
    assert normalize_answer("B,B,D") == "BBD"
    assert answer_number("X28_2") == "28"
    assert answer_for_split_question("X06_1", "AAAC") == "A"
    assert answer_for_split_question("X06_4", "AAAC") == "C"
    assert answer_for_split_question("X03_2", "B") == "B"


def test_fresh_ocr_is_required_for_automatic_release():
    assert classify_evidence("A", "A", None) == ("fresh_ocr_missing", True)
    assert classify_evidence("A", "A", "A") == ("verified", False)
    assert classify_evidence("A", "B", "B") == ("source_consensus_conflict", True)
    assert classify_evidence("A", "A", "B") == ("evidence_conflict", True)


def test_page_only_ocr_cache_is_rejected(tmp_path):
    image = tmp_path / "page_001.png"
    image.write_bytes(b"fake-png")
    cache = tmp_path / "page_001.json"
    cache.write_text(
        json.dumps({"page": 1, "backend": "CUDA", "blocks": []}), encoding="utf-8"
    )
    assert ocr_cache_valid(cache, image, engine_version="1.0") is False
    cache.write_text(
        json.dumps(
            {
                "page": 1,
                "protocol": OCR_CACHE_PROTOCOL,
                "engine_version": "1.0",
                "image_sha256": "deadbeef",
                "blocks": [],
            }
        ),
        encoding="utf-8",
    )
    assert ocr_cache_valid(cache, image, engine_version="1.0") is False
