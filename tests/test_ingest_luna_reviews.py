import json

import ingest_luna_reviews as ingest
import pytest


def _ledger(tmp_path, *, overall="pending", source_hash="hash-1"):
    path = tmp_path / "quality-ledger.json"
    payload = {
        "summary": {
            "total": 1,
            "certified": 0,
            "pending": int(overall == "pending"),
            "held": int(overall == "hold"),
        },
        "courses": {},
        "items": {
            "u1": {
                "source_uid": "u1",
                "source_hash": source_hash,
                "answer_choice": "B",
                "source_fidelity": "pending",
                "answer_validation": "pending",
                "overall": overall,
                "reason_codes": ["old_hold"] if overall == "hold" else [],
                "evidence": {},
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _packet(pass_id, rows, packet_hash="packet-1"):
    return {
        "protocol": "luna-review-v1",
        "pass_id": pass_id,
        "packet_hash": packet_hash,
        "items": rows,
    }


def _run(
    tmp_path,
    *,
    choice_a="B",
    choice_b="B",
    conf_a=0.9,
    conf_b=0.91,
    source_hash="hash-1",
    source_conf=0.9,
    source_ok=True,
    overall="pending",
    dry_run=False,
    adjudication=None,
    source_item=None,
):
    ledger = _ledger(tmp_path, overall=overall)
    common = {"source_uid": "u1", "source_hash": source_hash}
    blind_a = _packet("blind-a", [{**common, "choice": choice_a, "confidence": conf_a}])
    blind_b = _packet("blind-b", [{**common, "choice": choice_b, "confidence": conf_b}])
    source = _packet(
        "source",
        [
            {
                **common,
                **(
                    source_item
                    or {
                        "method": "ocr",
                        "source_verified": source_ok,
                        "confidence": source_conf,
                    }
                ),
            }
        ],
    )
    paths = []
    payloads = [("a.json", blind_a), ("b.json", blind_b), ("s.json", source)]
    if adjudication is not None:
        payloads.append(
            ("adj.json", _packet("adjudication", [{**common, **adjudication}]))
        )
    for name, payload in payloads:
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    written = []
    original = ingest.write_outputs
    ingest.write_outputs = lambda value: written.append(value)
    try:
        result = ingest.ingest_luna_reviews(
            paths[0],
            paths[1],
            paths[2],
            ledger_path=ledger,
            dry_run=dry_run,
            adjudication=paths[3] if adjudication is not None else None,
        )
    finally:
        ingest.write_outputs = original
    # quality_ledger.write_outputs receives the complete mutated ledger; tests do
    # not touch the real output files.
    state = written[0] if written else json.loads(ledger.read_text(encoding="utf-8"))
    return result, state, written


def test_three_way_consensus_certifies_and_writes_evidence(tmp_path):
    result, ledger, written = _run(tmp_path)
    item = ledger["items"]["u1"]
    assert result["certified"] == 1
    assert item["answer_validation"] == "verified"
    assert item["source_fidelity"] == "verified"
    assert item["overall"] == "certified"
    assert item["evidence"]["luna_reviews"]["blind_choices"] == ["B", "B"]
    assert len(written) == 1


def test_conflicting_blind_passes_hold(tmp_path):
    result, ledger, _ = _run(tmp_path, choice_b="C")
    item = ledger["items"]["u1"]
    assert result["held"] == 1
    assert item["overall"] == "hold"
    assert item["answer_validation"] == "conflict"
    assert "answer_conflict" in item["reason_codes"]


def test_choice_parser_accepts_only_letters_and_separators():
    assert ingest._choice("A、 C /D") == "ACD"
    assert ingest._choice("A,B") == "AB"
    assert ingest._choice("C……理由") == ""
    assert ingest._choice("答案：C") == ""
    assert ingest._choice("第3项") == ""


def test_rationale_mixed_into_choice_is_hold(tmp_path):
    result, ledger, _ = _run(tmp_path, choice_a="C……因为时间复杂度更低")
    item = ledger["items"]["u1"]
    assert result["certified"] == 0
    assert item["answer_validation"] == "conflict"
    assert item["overall"] == "hold"


def test_low_confidence_does_not_certify(tmp_path):
    result, ledger, _ = _run(tmp_path, conf_a=0.70 - 0.001)
    assert result["certified"] == 0
    assert ledger["items"]["u1"]["overall"] == "hold"


def test_old_hash_is_held_and_dry_run_does_not_write(tmp_path):
    result, ledger, written = _run(tmp_path, source_hash="old-hash", dry_run=True)
    assert result["held"] == 1
    assert result["results"][0]["reason"] == "stale_source_hash"
    assert written == []


def test_stale_source_hash_adds_stale_evidence_reason(tmp_path):
    _, ledger, _ = _run(tmp_path, source_hash="old-hash")
    item = ledger["items"]["u1"]
    assert item["overall"] == "hold"
    assert "stale_evidence" in item["reason_codes"]
    assert "luna_stale_source_hash" in item["reason_codes"]


def test_visual_pending_source_evidence_stays_pending_not_conflict(tmp_path):
    result, ledger, _ = _run(
        tmp_path,
        source_item={
            "method": "visual_pending",
            "source_verified": False,
            "confidence": 0,
        },
    )
    item = ledger["items"]["u1"]
    assert result["certified"] == 0
    assert item["source_fidelity"] == "pending"
    assert item["overall"] == "pending"
    assert "evidence_pending" in item["reason_codes"]
    assert "luna_source_conflict" not in item["reason_codes"]


def test_empty_source_observation_stays_pending_not_conflict(tmp_path):
    _, ledger, _ = _run(
        tmp_path,
        source_item={"method": "ocr", "source_verified": False, "confidence": 0},
    )
    item = ledger["items"]["u1"]
    assert item["source_fidelity"] == "pending"
    assert item["overall"] == "pending"
    assert "evidence_pending" in item["reason_codes"]
    assert "luna_source_conflict" not in item["reason_codes"]


def test_explicit_source_comparison_mismatch_holds_as_source_conflict(tmp_path):
    _, ledger, _ = _run(
        tmp_path,
        source_item={
            "method": "ocr",
            "source_verified": False,
            "confidence": 0.9,
            "content_match": False,
            "options_match": False,
            "answer_match": True,
        },
    )
    item = ledger["items"]["u1"]
    assert item["source_fidelity"] == "conflict"
    assert item["overall"] == "hold"
    assert "source_conflict" in item["reason_codes"]
    assert "luna_source_conflict" in item["reason_codes"]


def test_existing_hold_cannot_be_released_by_consensus(tmp_path):
    result, ledger, _ = _run(tmp_path, overall="hold")
    item = ledger["items"]["u1"]
    assert result["certified"] == 0
    assert item["overall"] == "hold"
    assert item["evidence"]["luna_reviews"]["reason"] == "existing_hold"


def test_adjudication_certify_releases_existing_hold_only_with_complete_evidence(
    tmp_path,
):
    result, ledger, _ = _run(
        tmp_path,
        overall="hold",
        adjudication={
            "action": "certify",
            "source_verified": True,
            "answer_verified": True,
        },
    )
    assert result["certified"] == 1
    assert ledger["items"]["u1"]["overall"] == "certified"


def test_adjudication_without_explicit_certify_keeps_hold(tmp_path):
    result, ledger, _ = _run(
        tmp_path,
        overall="hold",
        adjudication={
            "action": "hold",
            "source_verified": True,
            "answer_verified": True,
        },
    )
    assert result["certified"] == 0
    assert ledger["items"]["u1"]["overall"] == "hold"


def test_packet_hash_is_top_level_and_item_hash_is_not_packet_hash(tmp_path):
    ledger = _ledger(tmp_path)
    common = {"source_uid": "u1", "source_hash": "hash-1"}
    packets = [
        _packet(
            "blind-a",
            [{**common, "choice": "B", "confidence": 0.9, "item_hash": "item-a"}],
        ),
        _packet(
            "blind-b",
            [{**common, "choice": "B", "confidence": 0.9, "item_hash": "item-b"}],
        ),
        _packet(
            "source",
            [
                {
                    **common,
                    "method": "ocr",
                    "source_verified": True,
                    "confidence": 0.9,
                    "item_hash": "item-c",
                }
            ],
        ),
    ]
    paths = []
    for index, payload in enumerate(packets):
        path = tmp_path / f"packet-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    written = []
    original = ingest.write_outputs
    ingest.write_outputs = lambda value: written.append(value)
    try:
        result = ingest.ingest_luna_reviews(*paths, ledger_path=ledger)
    finally:
        ingest.write_outputs = original
    assert result["certified"] == 1
    assert (
        written[0]["items"]["u1"]["evidence"]["luna_reviews"]["packet_hashes"]
        == ["packet-1"] * 3
    )


def test_duplicate_source_uid_in_packet_is_structural_error(tmp_path):
    ledger = _ledger(tmp_path)
    common = {"source_uid": "u1", "source_hash": "hash-1"}
    blind_a = _packet("blind-a", [{**common, "choice": "B", "confidence": 0.9}])
    blind_b = _packet("blind-b", [{**common, "choice": "B", "confidence": 0.9}])
    source = _packet(
        "source",
        [
            {**common, "method": "ocr", "source_verified": True, "confidence": 0.9},
            {**common, "method": "ocr", "source_verified": True, "confidence": 0.9},
        ],
    )
    with pytest.raises(
        ingest.LunaReviewError, match="structural_error.*duplicate source_uid"
    ):
        ingest.ingest_luna_reviews(
            blind_a, blind_b, source, ledger_path=ledger, dry_run=True
        )


def test_formal_ocr_requires_triad_and_published_match(tmp_path):
    ledger = _ledger(tmp_path)
    common = {"source_uid": "u1", "source_hash": "hash-1"}
    packets = [
        _packet("blind-a", [{**common, "choice": "B", "confidence": 0.9}]),
        _packet("blind-b", [{**common, "choice": "B", "confidence": 0.9}]),
        _packet(
            "source",
            [
                {
                    **common,
                    "ocr": {"confidence": 0.9, "triad": True, "published_match": False},
                }
            ],
        ),
    ]
    paths = []
    for index, payload in enumerate(packets):
        path = tmp_path / f"ocr-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    result = ingest.ingest_luna_reviews(*paths, ledger_path=ledger, dry_run=True)
    assert result["certified"] == 0
    assert result["held"] == 1
