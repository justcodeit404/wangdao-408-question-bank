#!/usr/bin/env python3
"""Synchronize the resumable original-page review queue with durable evidence."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import MATH_BANK_DIR, PROJECT_ROOT

DEFAULT_QUEUE = PROJECT_ROOT.parents[1] / "temp" / "page-review" / "queue.json"
DEFAULT_LEDGER = MATH_BANK_DIR / "quality-ledger.json"
DEFAULT_PATCHES = PROJECT_ROOT / "data" / "quality" / "page_review_patches.json"
DEFAULT_EVIDENCE = PROJECT_ROOT / "data" / "quality" / "page_review_evidence.json"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _uid(course: str, chapter: str, qid: str) -> str:
    return f"408:cs408-{course}::{chapter}::{qid}"


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def sync_queue(
    queue_path: Path = DEFAULT_QUEUE,
    ledger_path: Path = DEFAULT_LEDGER,
    patches_path: Path = DEFAULT_PATCHES,
    evidence_path: Path = DEFAULT_EVIDENCE,
) -> dict[str, int]:
    queue = _read(queue_path, {})
    ledger = _read(ledger_path, {})
    if not isinstance(queue, dict) or not isinstance(queue.get("items"), list):
        raise ValueError(f"invalid page review queue: {queue_path}")
    ledger_items = ledger.get("items") if isinstance(ledger, dict) else {}
    if not isinstance(ledger_items, dict):
        raise ValueError(f"invalid quality ledger: {ledger_path}")
    patches = _read(patches_path, {})
    patch_uids = {
        _uid(str(row.get("course") or ""), str(row.get("chapter") or ""), str(row.get("qid") or ""))
        for row in (patches.get("items", []) if isinstance(patches, dict) else [])
        if isinstance(row, dict) and row.get("course") and row.get("chapter") and row.get("qid")
    }
    evidence = _read(evidence_path, {})
    latest: dict[str, dict[str, Any]] = {}
    for row in (evidence.get("records", []) if isinstance(evidence, dict) else []):
        if isinstance(row, dict) and row.get("source_uid"):
            latest[str(row["source_uid"])] = row

    for row in queue["items"]:
        if not isinstance(row, dict):
            raise ValueError("queue item is not an object")
        uid = str(row.get("source_uid") or "")
        current = ledger_items.get(uid)
        if not isinstance(current, dict):
            row["status"] = "stale"
            row["stale_reason"] = "missing_ledger_item"
            continue
        if str(row.get("source_hash") or "") != str(current.get("source_hash") or ""):
            # 补丁题的旧队列哈希来自修补前快照；补丁清单是该题已完成
            # 原书二查的依据，因此把队列绑定到新的发布哈希，而不是把
            # 已完成题误报为 stale。其它题目必须重新排队。
            if uid in patch_uids:
                row["source_hash"] = current.get("source_hash")
            else:
                row["status"] = "stale"
                row["stale_reason"] = "source_hash_changed"
                continue
        review = latest.get(uid)
        if uid in patch_uids and current.get("overall") == "certified":
            row["status"] = "patched_certified"
        elif review:
            action = str(review.get("final_action") or "hold")
            row["status"] = "reviewed_certified" if current.get("overall") == "certified" else f"reviewed_{action}"
        else:
            row["status"] = "ready"
        row["last_reviewed_at"] = review.get("reviewed_at") if review else None
        row["current_overall"] = current.get("overall")

    queue["updated_at"] = datetime.now(timezone.utc).isoformat()
    counts: dict[str, int] = {}
    for row in queue["items"]:
        status = str(row.get("status") or "ready")
        counts[status] = counts.get(status, 0) + 1
    queue["summary"] = counts
    _write(queue_path, queue)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--patches", type=Path, default=DEFAULT_PATCHES)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    print(json.dumps(sync_queue(args.queue, args.ledger, args.patches, args.evidence), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
