#!/usr/bin/env python3
"""Apply certifications backed by persisted original-page review records."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quality_ledger import LEDGER_PATH, _load_json, assert_consistent, write_outputs

DEFAULT_EVIDENCE = Path(__file__).resolve().parents[1] / "data" / "quality" / "page_review_evidence.json"

HOLD_CODES = {
    "legacy_hold_recheck", "source_conflict", "answer_conflict", "structural_check",
    "structural_error", "strict_hold", "human_hold", "luna_source_conflict",
    "luna_answer_conflict", "luna_stale_source_hash", "source_unreadable",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def apply(evidence_path: Path = DEFAULT_EVIDENCE, ledger_path: Path = LEDGER_PATH) -> dict[str, int]:
    evidence = _load_json(evidence_path, {})
    ledger = _load_json(ledger_path, {})
    items = ledger.get("items") if isinstance(ledger, dict) else None
    records = evidence.get("records") if isinstance(evidence, dict) else None
    if not isinstance(items, dict) or not isinstance(records, list):
        raise ValueError("invalid ledger or page review evidence")
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if isinstance(record, dict) and record.get("source_uid"):
            latest[str(record["source_uid"])] = record
    changed = 0
    for uid, record in latest.items():
        item = items.get(uid)
        if not isinstance(item, dict):
            raise ValueError(f"page review evidence UID not in ledger: {uid}")
        action = str(record.get("final_action") or "").lower()
        if action not in {"certify", "patch"}:
            continue
        if action == "patch" and record.get("post_patch_verified") is not True:
            continue
        source_hash = str(record.get("source_hash") or "")
        if not source_hash or source_hash != str(item.get("source_hash") or ""):
            continue
        if not record.get("q_pages_viewed") or not record.get("a_pages_viewed"):
            raise ValueError(f"page review evidence missing q/a pages: {uid}")
        item["source_fidelity"] = "verified"
        item["answer_validation"] = "verified"
        item["overall"] = "certified"
        item["reason_codes"] = sorted(set(item.get("reason_codes") or []) - HOLD_CODES)
        item["verified_at"] = record.get("reviewed_at") or _now()
        item.setdefault("evidence", {})["original_page_review"] = record
        changed += 1
    counts = {"certified": sum(item.get("overall") == "certified" for item in items.values()),
              "pending": sum(item.get("overall") == "pending" for item in items.values()),
              "held": sum(item.get("overall") == "hold" for item in items.values())}
    ledger["generated_at"] = _now()
    ledger["summary"] = {"total": len(items), **counts}
    assert_consistent(ledger)
    write_outputs(ledger)
    return {"changed": changed, **ledger["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    args = parser.parse_args()
    print(json.dumps(apply(args.evidence, args.ledger), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
