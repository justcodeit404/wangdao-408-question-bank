import json

import ingest_quality_decisions as ingest


def test_decisions_require_explicit_action(tmp_path, monkeypatch):
    ledger_path = tmp_path / "quality-ledger.json"
    payload = {
        "items": {"u1": {"source_fidelity": "pending", "answer_validation": "pending", "overall": "pending", "reason_codes": [], "evidence": {}}},
        "summary": {"total": 1, "certified": 0, "pending": 1, "held": 0},
        "courses": {},
    }
    input_path = tmp_path / "decisions.json"
    input_path.write_text(json.dumps({"items": [{"source_uid": "u1"}]}), encoding="utf-8")
    monkeypatch.setattr(ingest, "LEDGER_PATH", ledger_path)
    ledger_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        ingest.apply_decisions(input_path)
    except ValueError as exc:
        assert "缺少明确 action" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ambiguous human decisions must fail closed")
