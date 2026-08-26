#!/usr/bin/env python3
"""408 题库质量 ledger。

ledger 是题库质量状态的唯一来源；quality-hold.json 和
quality-verification.json 只是给旧构建/平台使用的派生清单。这个模块故意不
调用模型，只负责稳定的 UID、内容哈希、状态迁移和清单一致性。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from config import COURSES, MATH_BANK_DIR, REPORTS_DIR
from luna_review_v2 import apply_v2_fields
from quality_hold import _choice_should_hold, source_uid
from utils import write_json_atomic, write_text_atomic

LEDGER_PATH = MATH_BANK_DIR / "quality-ledger.json"
HOLD_PATH = MATH_BANK_DIR / "quality-hold.json"
VERIFICATION_PATH = MATH_BANK_DIR / "quality-verification.json"
LEDGER_JS_PATH = MATH_BANK_DIR / "quality-ledger.js"

TERMINAL_SOURCE = {"verified", "conflict"}
TERMINAL_ANSWER = {"verified", "conflict"}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def question_hash(question: Mapping[str, Any]) -> str:
    """只对会影响题目/答案可信度的内容做哈希。"""
    answer = (
        question.get("answer") if isinstance(question.get("answer"), Mapping) else {}
    )
    payload = {
        "id": question.get("id"),
        "type": question.get("type"),
        "content": question.get("content"),
        "options": question.get("options"),
        "answer": {
            "choice": answer.get("choice"),
            "explanation": answer.get("explanation"),
        },
        "has_image": bool(question.get("has_image")),
        "image_ref": question.get("image_ref"),
        "q_pages": question.get("q_pages"),
        "a_pages": question.get("a_pages"),
    }
    return _sha256_bytes(_canonical(payload).encode("utf-8"))


def _load_json(path: Path, default: Any) -> Any:
    try:
        return (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
        )
    except (OSError, json.JSONDecodeError):
        return default


def _published_path(course_key: str) -> Path:
    return MATH_BANK_DIR / f"data-{course_key}.json"


def iter_published_rows(
    course_key: str,
    data: Mapping[str, Any],
) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """遍历所有有题号的已发布题目。"""
    for chapter in data.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            continue
        chapter_name = str(chapter.get("name") or chapter.get("topic_title") or "")
        for question in chapter.get("questions") or []:
            if not isinstance(question, Mapping):
                continue
            qid = str(question.get("id") or "").strip()
            if not qid:
                continue
            yield source_uid(course_key, chapter_name, qid), chapter_name, question


def iter_choice_rows(
    course_key: str,
    data: Mapping[str, Any],
) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    for row in iter_published_rows(course_key, data):
        if "选择" in str(row[2].get("type") or ""):
            yield row


def published_uid_counts(course_key: str, data: Mapping[str, Any]) -> Counter[str]:
    """返回发布题目 UID 的出现次数，供构建前检查重复。"""
    return Counter(uid for uid, _, _ in iter_published_rows(course_key, data))


def _old_verified_records() -> dict[str, Mapping[str, Any]]:
    old = _load_json(VERIFICATION_PATH, {})
    rows = old.get("records") if isinstance(old, Mapping) else []
    records = {
        str(row.get("source_uid")): row
        for row in rows or []
        if isinstance(row, Mapping) and row.get("source_uid")
    }
    state = _load_json(REPORTS_DIR / "quality_verification_state.json", {})
    if isinstance(state, Mapping):
        for uid, verified_hash in (state.get("verified") or {}).items():
            records.setdefault(
                str(uid),
                {
                    "source_uid": str(uid),
                    "status": "verified",
                    "verified_hash": verified_hash,
                },
            )
        if not records:
            for row in state.get("last_records") or []:
                if isinstance(row, Mapping) and row.get("source_uid"):
                    records[str(row["source_uid"])] = row
    return records


def _record_matches_current(
    question: Mapping[str, Any], record: Mapping[str, Any]
) -> bool:
    """旧版本记录没有 verified_hash 时，用双读图字段确认补丁仍在当前题上。"""
    fields = record.get("fields") if isinstance(record.get("fields"), Mapping) else {}
    if not fields:
        return False
    if "content" in fields and str(fields.get("content")) != str(
        question.get("content")
    ):
        return False
    if "options" in fields and _canonical(fields.get("options")) != _canonical(
        question.get("options")
    ):
        return False
    answer = (
        question.get("answer") if isinstance(question.get("answer"), Mapping) else {}
    )
    if "answer.choice" in fields and str(fields.get("answer.choice")) != str(
        answer.get("choice")
    ):
        return False
    if "explanation" in fields and str(fields.get("explanation")) != str(
        answer.get("explanation")
    ):
        return False
    return True


def _old_hold_uids() -> set[str]:
    old = _load_json(HOLD_PATH, {})
    return {str(uid) for uid in (old.get("source_uids") or []) if str(uid).strip()}


def _new_item(
    *,
    uid: str,
    course_key: str,
    chapter: str,
    question: Mapping[str, Any],
    old: Mapping[str, Any] | None,
    old_verified: Mapping[str, Any] | None,
    old_holds: set[str],
) -> dict[str, Any]:
    current_hash = question_hash(question)
    structural = bool(_choice_should_hold(question))
    same_hash = bool(old and old.get("source_hash") == current_hash)
    old_row = old_verified.get(uid) if old_verified else None
    vision_verified = bool(
        old_row
        and (
            (old_row.get("verified_hash") or old_row.get("source_hash")) == current_hash
            or _record_matches_current(question, old_row)
        )
        and old_row.get("status") in {"verified", "auto_fixed"}
    )
    vision_held = bool(old_row and old_row.get("status") == "held" and same_hash)
    reasons = list(old.get("reason_codes") or []) if same_hash and old else []
    if structural or vision_held:
        reasons = sorted(
            set(reasons) | ({"structural_check"} if structural else {"vision_conflict"})
        )
        source_status = "conflict"
        answer_status = "conflict"
        overall = "hold"
    elif vision_verified:
        source_status = "verified"
        answer_status = (
            str(old.get("answer_validation") or "pending")
            if same_hash and old
            else "pending"
        )
        overall = (
            str(old.get("overall") or "pending") if same_hash and old else "pending"
        )
    elif same_hash and old:
        source_status = str(old.get("source_fidelity") or "pending")
        answer_status = str(old.get("answer_validation") or "pending")
        overall = str(old.get("overall") or "pending")
    else:
        # 旧视觉门禁只证明了转录，不代表独立盲解已完成。
        source_status = "verified" if vision_verified else "pending"
        answer_status = "pending"
        overall = "pending"
        reasons = []
    if uid in old_holds and not structural and not same_hash:
        # 历史隔离是迁移证据，但内容变化后重新进入 pending，避免永久污染。
        reasons.append("legacy_hold_recheck")
    answer = (
        question.get("answer") if isinstance(question.get("answer"), Mapping) else {}
    )
    row = {
        "source_uid": uid,
        "course_key": course_key,
        "chapter": chapter,
        "question_id": str(question.get("id") or ""),
        "source_hash": current_hash,
        "source_fidelity": source_status,
        "answer_validation": answer_status,
        "overall": overall
        if overall in {"pending", "certified", "hold"}
        else "pending",
        "reason_codes": sorted(set(str(x) for x in reasons if str(x).strip())),
        "q_pages": list(question.get("q_pages") or []),
        "a_pages": list(question.get("a_pages") or []),
        "has_image": bool(question.get("has_image") or question.get("image_ref")),
        "answer_choice": str(answer.get("choice") or ""),
        "verified_at": old.get("verified_at") if same_hash and old else None,
        "evidence": dict(old.get("evidence") or {}) if same_hash and old else {},
    }
    apply_v2_fields(row, question)
    return row


def _recompute_overall(item: dict[str, Any], strict: bool = False) -> None:
    if item["source_fidelity"] == "conflict" or item["answer_validation"] == "conflict":
        item["overall"] = "hold"
    elif (
        item["source_fidelity"] == "verified"
        and item["answer_validation"] == "verified"
    ):
        item["overall"] = "certified"
    else:
        item["overall"] = "hold" if strict else "pending"


def build_ledger(*, strict_courses: set[str] | None = None) -> dict[str, Any]:
    """从当前发布 JSON 重算 ledger；旧状态只在 source_hash 未变时保留。"""
    old_ledger = _load_json(LEDGER_PATH, {})
    old_items = old_ledger.get("items") if isinstance(old_ledger, Mapping) else {}
    old_items = old_items if isinstance(old_items, Mapping) else {}
    old_verified = _old_verified_records()
    old_holds = _old_hold_uids()
    previous_courses = (
        old_ledger.get("courses") if isinstance(old_ledger, Mapping) else {}
    )
    previous_courses = previous_courses if isinstance(previous_courses, Mapping) else {}
    strict_courses = (
        strict_courses
        if strict_courses is not None
        else {
            key
            for key, value in previous_courses.items()
            if isinstance(value, Mapping) and value.get("mode") == "strict"
        }
    )
    items: dict[str, dict[str, Any]] = {}
    courses: dict[str, dict[str, Any]] = {}
    published_hashes: dict[str, str] = {}
    for course in COURSES:
        path = _published_path(course.key)
        if not path.is_file():
            continue
        data = _load_json(path, {})
        published_hashes[course.key] = sha256_file(path)
        rows = iter_published_rows(course.key, data)
        for uid, chapter, question in rows:
            if uid in items:
                item = items[uid]
                item["source_fidelity"] = "conflict"
                item["answer_validation"] = "conflict"
                item["reason_codes"] = sorted(
                    set(item["reason_codes"]) | {"structural_error", "duplicate_uid"}
                )
                _recompute_overall(item, course.key in strict_courses)
                continue
            item = _new_item(
                uid=uid,
                course_key=course.key,
                chapter=chapter,
                question=question,
                old=old_items.get(uid) if isinstance(old_items, Mapping) else None,
                old_verified=old_verified,
                old_holds=old_holds,
            )
            _recompute_overall(item, course.key in strict_courses)
            items[uid] = item
        counts = Counter(
            item["overall"]
            for item in items.values()
            if item["course_key"] == course.key
        )
        courses[course.key] = {
            "name": course.name,
            "mode": "strict" if course.key in strict_courses else "progressive",
            "total": sum(counts.values()),
            "certified": counts.get("certified", 0),
            "pending": counts.get("pending", 0),
            "held": counts.get("hold", 0),
        }
    summary = Counter(item["overall"] for item in items.values())
    ledger = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "published_hashes": published_hashes,
        "courses": courses,
        "summary": {
            "total": len(items),
            "certified": summary.get("certified", 0),
            "pending": summary.get("pending", 0),
            "held": summary.get("hold", 0),
        },
        "items": dict(sorted(items.items())),
    }
    assert_consistent(ledger)
    return ledger


def assert_consistent(ledger: Mapping[str, Any]) -> None:
    items = ledger.get("items") or {}
    summary = ledger.get("summary") or {}
    counts = Counter(
        str(item.get("overall")) for item in items.values() if isinstance(item, Mapping)
    )
    expected = {
        "total": len(items),
        "certified": counts.get("certified", 0),
        "pending": counts.get("pending", 0),
        "held": counts.get("hold", 0),
    }
    actual = {key: int(summary.get(key, -1)) for key in expected}
    if expected != actual:
        raise ValueError(
            f"quality ledger summary mismatch: expected={expected} actual={actual}"
        )
    for uid, item in items.items():
        if item.get("source_uid") != uid:
            raise ValueError(f"quality ledger UID mismatch: {uid}")
        if item.get("overall") == "certified" and not (
            item.get("source_fidelity") == "verified"
            and item.get("answer_validation") == "verified"
        ):
            raise ValueError(f"certified item is not dual verified: {uid}")
    source_uids = [str(item.get("source_uid")) for item in items.values()]
    if len(source_uids) != len(set(source_uids)):
        raise ValueError("quality ledger contains duplicate source UIDs")
    for course, data in (ledger.get("courses") or {}).items():
        if data.get("mode") == "strict" and int(data.get("pending", 0)):
            raise ValueError(f"strict course has pending items: {course}")


def derive_manifests(
    ledger: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assert_consistent(ledger)
    items = ledger.get("items") or {}
    hold_uids = sorted(
        uid for uid, item in items.items() if item.get("overall") == "hold"
    )
    hashes = dict(ledger.get("published_hashes") or {})
    hold = {
        "schema_version": 3,
        "ledger_sha256": _sha256_bytes(_canonical(ledger).encode("utf-8")),
        "source_hashes": hashes,
        "source_uids": hold_uids,
        "summary": {
            "held": len(hold_uids),
            "note": "derived from quality-ledger.json",
            "courses": sorted((ledger.get("courses") or {}).keys()),
        },
    }
    verification = {
        "schema_version": 2,
        "status": "published",
        "generated_at": ledger.get("generated_at"),
        "round_id": "ledger",
        "summary": dict(ledger.get("summary") or {}),
        "published_hashes": hashes,
        "ledger_sha256": hold["ledger_sha256"],
        "courses": ledger.get("courses") or {},
    }
    # 保留旧视觉门禁的逐题记录，供 audit-only、追溯和下一次 ledger 迁移使用。
    previous = _load_json(VERIFICATION_PATH, {})
    records = previous.get("records") if isinstance(previous, Mapping) else []
    if not records:
        state = _load_json(REPORTS_DIR / "quality_verification_state.json", {})
        records = state.get("last_records") if isinstance(state, Mapping) else []
    if isinstance(records, list) and records:
        verification["records"] = records
    return hold, verification


def write_outputs(ledger: Mapping[str, Any]) -> None:
    MATH_BANK_DIR.mkdir(parents=True, exist_ok=True)
    hold, verification = derive_manifests(ledger)
    write_json_atomic(LEDGER_PATH, ledger, indent=2, ensure_ascii=False)
    write_json_atomic(HOLD_PATH, hold, indent=2, ensure_ascii=False)
    write_json_atomic(VERIFICATION_PATH, verification, indent=2, ensure_ascii=False)
    wrapper = "// Auto-generated; do not edit by hand.\nwindow.__QUALITY_LEDGER__ = "
    wrapper += json.dumps(ledger, ensure_ascii=False, separators=(",", ":")) + ";\n"
    write_text_atomic(LEDGER_JS_PATH, wrapper, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="重算 408 质量 ledger 和兼容清单")
    parser.add_argument(
        "--strict-course", action="append", default=[], choices=[c.key for c in COURSES]
    )
    args = parser.parse_args()
    ledger = build_ledger(strict_courses=set(args.strict_course) or None)
    write_outputs(ledger)
    print(json.dumps(ledger["summary"], ensure_ascii=False, indent=2))
    print(f"ledger: {LEDGER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
