import json

import pytest

from page_review_evidence import build_evidence, normalize_row


def test_normalize_review_records_page_hashes(tmp_path):
    q_page = tmp_path / "q.png"
    a_page = tmp_path / "a.png"
    q_page.write_bytes(b"question")
    a_page.write_bytes(b"answer")
    row = normalize_row({
        "source_uid": "u1",
        "q_pages_viewed": [str(q_page)],
        "a_pages_viewed": [str(a_page)],
        "final_action": "certify",
        "content_match": True,
        "options_match": True,
        "answer_match": True,
    })
    assert row["q_pages_viewed"][0]["sha256"]
    assert row["a_pages_viewed"][0]["sha256"]
    assert row["protocol"] == "codex-original-page-review-v1"


def test_normalize_review_rejects_missing_page(tmp_path):
    with pytest.raises(ValueError, match="page missing"):
        normalize_row({
            "source_uid": "u1",
            "q_pages_viewed": [str(tmp_path / "missing.png")],
            "a_pages_viewed": [str(tmp_path / "missing-a.png")],
            "final_action": "hold",
        })


def test_build_evidence_deduplicates_same_review():
    row = {
        "source_uid": "u1",
        "reviewed_at": "2026-08-26T00:00:00+00:00",
        "final_action": "hold",
    }
    packet = build_evidence([row, row], {"records": [row]})
    assert len(packet["records"]) == 1
