#!/usr/bin/env python3
"""把质检页导出的人工裁决摄入 quality-ledger。

导出文件必须显式包含 action：certify、hold、source_verified 或 answer_verified。
没有 action 的历史回归文件不会被猜测处理，避免把“已修复”误当成答案已验算。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from quality_ledger import LEDGER_PATH, _load_json, _utc_now, assert_consistent, write_outputs
from utils import write_json_atomic


def apply_decisions(path: Path, *, default_action: str | None = None) -> dict:
    payload = _load_json(path, {})
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("裁决文件必须是 {items:[...]} 或数组")
    ledger = _load_json(LEDGER_PATH, {})
    items = ledger.get("items") if isinstance(ledger, dict) else None
    if not isinstance(items, dict):
        raise ValueError("缺少 quality-ledger.json")
    changed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = str(row.get("source_uid") or "")
        item = items.get(uid)
        if not uid or not isinstance(item, dict):
            raise ValueError(f"裁决 UID 不在当前 ledger: {uid}")
        action = str(row.get("action") or default_action or "").strip()
        if action not in {"certify", "hold", "source_verified", "answer_verified"}:
            raise ValueError(f"{uid} 缺少明确 action（certify/hold/source_verified/answer_verified）")
        if action == "hold":
            item["source_fidelity"] = "conflict"
            item["answer_validation"] = "conflict"
            item["overall"] = "hold"
            item.setdefault("reason_codes", []).append("human_hold")
        elif action == "source_verified":
            item["source_fidelity"] = "verified"
            item["overall"] = "certified" if item.get("answer_validation") == "verified" else "pending"
        elif action == "answer_verified":
            item["answer_validation"] = "verified"
            item["overall"] = "certified" if item.get("source_fidelity") == "verified" else "pending"
        else:
            item["source_fidelity"] = "verified"
            item["answer_validation"] = "verified"
            item["overall"] = "certified"
        item["reason_codes"] = sorted(set(str(x) for x in item.get("reason_codes") or [] if str(x).strip()))
        item["verified_at"] = _utc_now()
        item.setdefault("evidence", {})["human_action"] = action
        if row.get("evidence"):
            item["evidence"]["human_evidence"] = str(row["evidence"])
        changed += 1
    counts = Counter(item.get("overall") for item in items.values())
    ledger["generated_at"] = _utc_now()
    ledger["summary"] = {
        "total": len(items), "certified": counts.get("certified", 0),
        "pending": counts.get("pending", 0), "held": counts.get("hold", 0),
    }
    assert_consistent(ledger)
    write_outputs(ledger)
    return {"changed": changed, **ledger["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--default-action", choices=["certify", "hold", "source_verified", "answer_verified"])
    args = parser.parse_args()
    result = apply_decisions(args.input, default_action=args.default_action)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
