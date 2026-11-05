#!/usr/bin/env python3
"""Apply certifications backed by persisted original-page review records."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import COURSES
from quality_ledger import (
    LEDGER_PATH,
    _load_json,
    _published_path,
    assert_consistent,
    iter_published_rows,
    question_hash,
    write_outputs,
)

DEFAULT_EVIDENCE = (
    Path(__file__).resolve().parents[1] / "data" / "quality" / "page_review_evidence.json"
)

HOLD_CODES = {
    "legacy_hold_recheck",
    "source_conflict",
    "answer_conflict",
    "structural_check",
    "structural_error",
    "strict_hold",
    "human_hold",
    "luna_source_conflict",
    "luna_answer_conflict",
    "luna_stale_source_hash",
    "source_unreadable",
    # 「未登记发布」在认证落地后即失效，留着会让已认证题带着 hold 语义。
    "unregistered_publication",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _review_rank(record: dict[str, Any]) -> str:
    """把迁移的历史占位记录排在真实复核记录之前。"""
    reviewed_at = str(record.get("reviewed_at") or "")
    return "" if reviewed_at.startswith("migrated:") else reviewed_at


def published_hash_sync_allowed(
    *,
    uid: str,
    record: dict[str, Any],
    item_source_hash: str,
    published_hash: str,
    allow_uids: set[str],
) -> bool:
    """补丁已核对、证据哈希等于当前发布题，才允许把账本旧哈希改成发布哈希。

    ``certify`` 不能走这条路。不在本轮 UID 名单里的题、证据哈希对不上发布题的，
    一律拒绝，避免用一次刷新把未审查的漂移吸进账本。
    """
    if uid not in allow_uids:
        return False
    if str(record.get("final_action") or "").lower() != "patch":
        return False
    if record.get("post_patch_verified") is not True:
        return False
    source_hash = str(record.get("source_hash") or "")
    if not source_hash or not published_hash or source_hash != published_hash:
        return False
    return source_hash != item_source_hash


def _published_subset(uids: set[str]) -> dict[str, dict[str, Any]]:
    """只读取名单内题目的当前发布哈希和题面。"""
    found: dict[str, dict[str, Any]] = {}
    if not uids:
        return found
    for course in COURSES:
        data = _load_json(_published_path(course.key), {})
        for uid, _chapter, question in iter_published_rows(course.key, data):
            if uid not in uids:
                continue
            found[uid] = {"hash": question_hash(question), "question": question}
        if len(found) == len(uids):
            break
    return found


def _adopt_published_question(
    item: dict[str, Any], question: dict[str, Any], published_hash: str
) -> None:
    answer = question.get("answer") if isinstance(question.get("answer"), dict) else {}
    item["source_hash"] = published_hash
    item["q_pages"] = list(question.get("q_pages") or [])
    item["a_pages"] = list(question.get("a_pages") or [])
    item["has_image"] = bool(question.get("has_image") or question.get("image_ref"))
    item["answer_choice"] = str((answer or {}).get("choice") or "")


def apply(
    evidence_path: Path = DEFAULT_EVIDENCE,
    ledger_path: Path = LEDGER_PATH,
    sync_uids: set[str] | None = None,
    published_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, int]:
    evidence = _load_json(evidence_path, {})
    ledger = _load_json(ledger_path, {})
    allow_sync = set(sync_uids or [])
    published = published_index if published_index is not None else _published_subset(allow_sync)
    items = ledger.get("items") if isinstance(ledger, dict) else None
    records = evidence.get("records") if isinstance(evidence, dict) else None
    if not isinstance(items, dict) or not isinstance(records, list):
        raise ValueError("invalid ledger or page review evidence")
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if isinstance(record, dict) and record.get("source_uid"):
            uid = str(record["source_uid"])
            if uid not in latest or _review_rank(record) >= _review_rank(latest[uid]):
                latest[uid] = record
    changed = 0
    synced = 0
    orphans: list[str] = []
    for uid, record in latest.items():
        item = items.get(uid)
        if not isinstance(item, dict):
            # 证据是只增历史：改号/删除题会留下账本里已不存在的 UID，
            # 这里跳过并汇报，不能因为一条孤儿记录让整批认证失败。
            orphans.append(uid)
            continue
        # 视觉记录不能绕过当前发布数据的结构门禁。选项缺失、非法
        # choice 等 structural_* 题必须先有可复现补丁并重建消除结构错误，
        # 否则严格 ledger 会把它保留为 hold，造成应用计数与正式账本漂移。
        if any(str(code).startswith("structural_") for code in (item.get("reason_codes") or [])):
            continue
        action = str(record.get("final_action") or "").lower()
        if action not in {"certify", "patch"}:
            continue
        if action == "patch" and record.get("post_patch_verified") is not True:
            continue
        source_hash = str(record.get("source_hash") or "")
        item_hash = str(item.get("source_hash") or "")
        if not source_hash:
            continue
        if source_hash != item_hash:
            pub = published.get(uid) or {}
            published_hash = str(pub.get("hash") or "")
            if not published_hash_sync_allowed(
                uid=uid,
                record=record,
                item_source_hash=item_hash,
                published_hash=published_hash,
                allow_uids=allow_sync,
            ):
                continue
            question = pub.get("question")
            if not isinstance(question, dict):
                continue
            _adopt_published_question(item, question, published_hash)
            synced += 1
        if not record.get("q_pages_viewed") or not record.get("a_pages_viewed"):
            raise ValueError(f"page review evidence missing q/a pages: {uid}")
        item["source_fidelity"] = "verified"
        item["answer_validation"] = "verified"
        item["overall"] = "certified"
        item["reason_codes"] = sorted(set(item.get("reason_codes") or []) - HOLD_CODES)
        item["verified_at"] = record.get("reviewed_at") or _now()
        item.setdefault("evidence", {})["original_page_review"] = record
        changed += 1
    counts = {
        "certified": sum(item.get("overall") == "certified" for item in items.values()),
        "pending": sum(item.get("overall") == "pending" for item in items.values()),
        "held": sum(item.get("overall") == "hold" for item in items.values()),
    }
    ledger["generated_at"] = _now()
    ledger["summary"] = {"total": len(items), **counts}
    # courses 必须与 items 同源重算：只改全局 summary 会让分科计数停在认证前的旧值。
    for course, data in (ledger.get("courses") or {}).items():
        if not isinstance(data, dict):
            continue
        course_counts = Counter(
            item.get("overall") for item in items.values() if item.get("course_key") == course
        )
        data.update(
            total=sum(course_counts.values()),
            certified=course_counts.get("certified", 0),
            pending=course_counts.get("pending", 0),
            held=course_counts.get("hold", 0),
        )
    assert_consistent(ledger)
    write_outputs(ledger)
    return {"changed": changed, "synced": synced, "orphans": len(orphans), **ledger["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument(
        "--sync-published-uids",
        default="",
        help="逗号分隔的本轮 UID。仅这些题在 patch 且 post_patch_verified 时，可把账本哈希改成当前发布哈希",
    )
    args = parser.parse_args()
    sync_uids = {uid.strip() for uid in args.sync_published_uids.split(",") if uid.strip()}
    print(
        json.dumps(
            apply(args.evidence, args.ledger, sync_uids=sync_uids), ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
