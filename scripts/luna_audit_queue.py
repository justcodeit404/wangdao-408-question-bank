#!/usr/bin/env python3
"""Offline, resumable audit queue for the 408 question bank.

This module deliberately has no model/network dependency.  It turns the four
published ``data-*.json`` files and ``quality-ledger.json`` into deterministic
blind-solution and visual-audit packets.  The blind packet is constructed from
an allow-list, rather than redacting a copy of a question, so answer fields
cannot accidentally cross the audit boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

COURSES = ("ds", "coa", "os", "net")
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "math-bank"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "temp" / "luna-audit"
SENSITIVE_KEYS = {"answer", "explanation", "a_pages", "answer_pages", "answer_page"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def source_uid(course: str, chapter: str, question_id: str) -> str:
    """Return the same UID shape used by the 408 platform importer."""
    return f"408:cs408-{course}::{chapter}::{question_id}"


def _question_image(question: Mapping[str, Any]) -> str | None:
    image = question.get("image_ref")
    if isinstance(image, Mapping) and image.get("cropped"):
        return str(image["cropped"])
    return None


def safe_question(question: Mapping[str, Any]) -> dict[str, Any]:
    """Copy solver-visible fields, including only the question image/page refs."""
    allowed = ("id", "type", "content", "options", "sub_questions")
    value = {key: question.get(key) for key in allowed if key in question}
    value["q_pages"] = list(question.get("q_pages") or [])
    image = _question_image(question)
    if image:
        value["question_image"] = image
    return value


def question_hash(question: Mapping[str, Any], uid: str | None = None) -> str:
    """Hash the solver-visible question; source answers/pages are excluded."""
    payload: dict[str, Any] = {"question": safe_question(question)}
    if uid:
        payload["source_uid"] = uid
    return _sha(payload)


def source_hash(question: Mapping[str, Any]) -> str:
    """Match quality_ledger.question_hash, including the published answer."""
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
    return _sha(payload)


def _risk(
    item: Mapping[str, Any], question: Mapping[str, Any]
) -> tuple[str, int, list[str]]:
    reasons = {str(x) for x in (item.get("reason_codes") or []) if str(x)}
    overall = str(item.get("overall") or "pending")
    source = str(item.get("source_fidelity") or "pending")
    answer_status = str(item.get("answer_validation") or "pending")
    score = 0
    if overall == "hold":
        score += 100
        reasons.add("ledger_hold")
    if source == "conflict" or answer_status == "conflict":
        score += 80
        reasons.add("quality_conflict")
    if "missing_ledger_item" in reasons:
        score += 70
    if question.get("has_image") or question.get("image_ref"):
        score += 25
        reasons.add("visual_evidence")
    if not str(question.get("content") or "").strip():
        score += 50
        reasons.add("empty_stem")
    if not isinstance(question.get("options"), Mapping) and "选择" in str(
        question.get("type") or ""
    ):
        score += 30
        reasons.add("missing_options")
    if score >= 100:
        tier = "critical"
    elif score >= 50:
        tier = "high"
    elif score >= 20:
        tier = "medium"
    else:
        tier = "low"
    return tier, score, sorted(reasons)


def iter_questions(
    root: Path = DEFAULT_ROOT,
    courses: Iterable[str] = COURSES,
    *,
    include_untracked: bool = False,
) -> list[dict[str, Any]]:
    """Load ledger-backed rows; untracked published questions are omitted by default."""
    ledger = _read(root / "quality-ledger.json", {})
    ledger_items = ledger.get("items") if isinstance(ledger, Mapping) else {}
    ledger_items = ledger_items if isinstance(ledger_items, Mapping) else {}
    rows: list[dict[str, Any]] = []
    for course in sorted(set(courses)):
        if course not in COURSES:
            raise ValueError(f"unknown course: {course}")
        data = _read(root / f"data-{course}.json", {})
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
                uid = source_uid(course, chapter_name, qid)
                item = ledger_items.get(uid)
                tracked_item = isinstance(item, Mapping)
                item = (
                    dict(item)
                    if tracked_item
                    else {"reason_codes": ["missing_ledger_item"]}
                )
                current_source_hash = source_hash(question)
                ledger_source_hash = str(item.get("source_hash") or "")
                hash_matches = (
                    not ledger_source_hash or ledger_source_hash == current_source_hash
                )
                tracked = tracked_item and hash_matches
                if not tracked:
                    if not tracked_item:
                        item.setdefault("reason_codes", []).append(
                            "missing_ledger_item"
                        )
                    else:
                        item.setdefault("reason_codes", []).append(
                            "source_hash_mismatch"
                        )
                    if not include_untracked:
                        continue
                tier, score, reasons = _risk(item, question)
                published_hash = ledger_source_hash or current_source_hash
                rows.append(
                    {
                        "source_uid": uid,
                        "course": course,
                        "chapter": chapter_name,
                        "question": dict(question),
                        "question_hash": question_hash(question, uid),
                        "source_hash": published_hash,
                        "tracked": tracked,
                        "risk_tier": tier,
                        "risk_score": score,
                        "risk_reasons": reasons,
                    }
                )
    rows.sort(key=lambda row: (-int(row["risk_score"]), str(row["source_uid"])))
    return rows


def untracked_report(
    root: Path = DEFAULT_ROOT, courses: Iterable[str] = COURSES
) -> list[dict[str, Any]]:
    """Return published rows excluded from the ingest-safe default queue."""
    rows = iter_questions(root, courses, include_untracked=True)
    return [
        {
            key: row[key]
            for key in (
                "source_uid",
                "course",
                "chapter",
                "source_hash",
                "risk_tier",
                "risk_reasons",
            )
        }
        for row in rows
        if not row.get("tracked")
    ]


def _packet_base(row: Mapping[str, Any], pass_id: str, kind: str) -> dict[str, Any]:
    packet = {
        "schema_version": 1,
        "packet_type": kind,
        "pass_id": pass_id,
        "course": row["course"],
        "source_uid": row["source_uid"],
        "source_hash": row["source_hash"],
        "question_hash": row["question_hash"],
    }
    return packet


def make_blind_packet(row: Mapping[str, Any], pass_id: str) -> dict[str, Any]:
    """Build a packet whose allow-listed payload contains no answer/page data."""
    packet = _packet_base(row, pass_id, "blind-solution")
    packet["question"] = safe_question(row["question"])
    packet["packet_hash"] = _sha(packet)
    return packet


def make_visual_packet(row: Mapping[str, Any], pass_id: str) -> dict[str, Any]:
    """Build a visual packet containing the complete published question snapshot."""
    question = row["question"]
    packet = _packet_base(row, pass_id, "visual-audit")
    image = question.get("image_ref")
    visual: dict[str, Any] = {
        "question": json.loads(json.dumps(question, ensure_ascii=False)),
        "q_pages": list(question.get("q_pages") or []),
        "a_pages": list(question.get("a_pages") or []),
    }
    if isinstance(image, Mapping):
        visual["question_image"] = json.loads(json.dumps(image, ensure_ascii=False))
        if image.get("box") is not None:
            visual["box"] = image["box"]
    packet["visual"] = visual
    packet["packet_hash"] = _sha(packet)
    return packet


def _manifest(
    rows: list[dict[str, Any]], pass_id: str, batch_size: int
) -> dict[str, Any]:
    records = [
        {
            key: row[key]
            for key in (
                "source_uid",
                "course",
                "chapter",
                "source_hash",
                "question_hash",
                "risk_tier",
                "risk_score",
                "risk_reasons",
            )
        }
        for row in rows
    ]
    manifest = {
        "schema_version": 1,
        "pass_id": pass_id,
        "batch_size": batch_size,
        "items": records,
    }
    manifest["queue_hash"] = _sha(manifest)
    return manifest


def _batch_packet(
    packet_type: str, pass_id: str, batch_id: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Wrap item packets and give every item the ingest batch hash.

    The nested ``packet_hash`` values are intentionally excluded while hashing
    the envelope: they are the envelope hash itself and would otherwise create
    a hash fixed-point problem.  The original per-item hash remains available
    as ``item_hash`` for diagnostics.
    """
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        normalized = dict(item)
        if normalized.get("packet_hash"):
            normalized["item_hash"] = normalized.pop("packet_hash")
        normalized_items.append(normalized)
    packet: dict[str, Any] = {
        "schema_version": 1,
        "packet_type": packet_type,
        "pass_id": pass_id,
        "batch_id": batch_id,
        "items": normalized_items,
    }
    packet["packet_hash"] = _sha(packet)
    for item in normalized_items:
        item["packet_hash"] = packet["packet_hash"]
    return packet


def validate_queue_state(
    state: Mapping[str, Any], rows: Iterable[Mapping[str, Any]] | None = None
) -> None:
    """Reject duplicate or stale UIDs before a queue state is persisted or resumed."""
    items = state.get("items")
    if not isinstance(items, list):
        raise ValueError("queue state missing items")
    source_uids = [
        str(item.get("source_uid") or "") for item in items if isinstance(item, Mapping)
    ]
    if len(source_uids) != len(items) or not all(source_uids):
        raise ValueError("queue state item missing source_uid")
    if len(set(source_uids)) != len(source_uids):
        raise ValueError("queue state has duplicate source_uid")
    source_hashes = {
        str(item.get("source_uid")): str(item.get("source_hash") or "")
        for item in items
        if isinstance(item, Mapping)
    }
    if not all(source_hashes.values()):
        raise ValueError("queue state item missing source_hash")
    if rows is not None:
        published_hashes = {
            str(row.get("source_uid") or ""): str(row.get("source_hash") or "")
            for row in rows
        }
        if source_hashes != published_hashes:
            raise ValueError(
                "queue state source_hash does not match current published source_hash"
            )
    for batch_key in ("batches", "visual_batches"):
        emitted: set[str] = set()
        for batch in state.get(batch_key) or []:
            if not isinstance(batch, Mapping):
                raise ValueError(f"queue state malformed {batch_key}")
            for uid in batch.get("source_uids") or []:
                normalized = str(uid)
                if not normalized or normalized in emitted:
                    raise ValueError(
                        f"queue state has duplicate emitted source_uid in {batch_key}"
                    )
                emitted.add(normalized)


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in SENSITIVE_KEYS or _contains_sensitive_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(child) for child in value)
    return False


def validate_batch(
    packet: Mapping[str, Any], published_hashes: Mapping[str, str] | None = None
) -> None:
    """Reject malformed, duplicate, stale, or answer-leaking emitted packets."""
    packet_hash = str(packet.get("packet_hash") or "")
    items = packet.get("items")
    if not packet_hash:
        raise ValueError("batch missing packet_hash")
    if not isinstance(items, list):
        raise ValueError("batch missing items")
    source_uids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("batch item is not an object")
        uid = str(item.get("source_uid") or "")
        if not uid:
            raise ValueError("batch item missing source_uid")
        if uid in source_uids:
            raise ValueError("batch has duplicate source_uid")
        source_uids.add(uid)
        if not str(item.get("source_hash") or ""):
            raise ValueError("batch item missing source_hash")
        if not str(item.get("item_hash") or ""):
            raise ValueError("batch item missing item_hash")
        if item.get("packet_hash") != packet_hash:
            raise ValueError("batch item packet_hash mismatch")
        if published_hashes is not None and item["source_hash"] != published_hashes.get(
            uid
        ):
            raise ValueError("batch source_hash mismatch current published source_hash")
    if str(packet.get("packet_type") or "").startswith(
        "blind"
    ) and _contains_sensitive_key(packet):
        raise ValueError("blind batch contains answer fields")


def initialize(
    *,
    root: Path = DEFAULT_ROOT,
    output_dir: Path = DEFAULT_OUTPUT,
    courses: Iterable[str] = COURSES,
    pass_id: str = "pass-1",
    batch_size: int | None = None,
    kind: str = "both",
    include_untracked: bool = False,
) -> dict[str, Any]:
    if kind not in {"blind", "visual", "both"}:
        raise ValueError("kind must be blind, visual, or both")
    blind_size = int(batch_size or (8 if kind == "visual" else 50))
    visual_size = int(batch_size or 8)
    if blind_size < 1 or visual_size < 1:
        raise ValueError("batch_size must be positive")
    course_list = tuple(courses)
    all_rows = iter_questions(root, course_list, include_untracked=True)
    omitted = [row for row in all_rows if not row.get("tracked")]
    rows = (
        all_rows
        if include_untracked
        else [row for row in all_rows if row.get("tracked")]
    )
    if kind == "visual":
        rows = [row for row in rows if row["risk_tier"] != "low"]
    manifest = _manifest(rows, pass_id, blind_size)
    state = {
        **manifest,
        "kind": kind,
        "visual_batch_size": visual_size,
        "courses": sorted(set(course_list)),
        "include_untracked": include_untracked,
        "omitted_untracked": len(omitted),
        "omitted_uids": [row["source_uid"] for row in omitted],
        "next_index": 0,
        "visual_next_index": 0,
        "batches": [],
        "visual_batches": [],
        "status": "ready",
    }
    validate_queue_state(state, rows)
    _atomic_json(output_dir / f"state-{pass_id}.json", state)
    return state


def resume(
    *,
    root: Path = DEFAULT_ROOT,
    output_dir: Path = DEFAULT_OUTPUT,
    pass_id: str = "pass-1",
    batch_size: int | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    state_path = output_dir / f"state-{pass_id}.json"
    state = _read(state_path, None)
    if not isinstance(state, dict):
        raise FileNotFoundError(f"queue not initialized: {state_path}")
    validate_queue_state(state)
    state_kind = str(kind or state.get("kind") or "both")
    if state_kind not in {"blind", "visual", "both"}:
        raise ValueError("kind must be blind, visual, or both")
    tracked_courses = [str(x) for x in state.get("courses", []) if str(x) in COURSES]
    if not tracked_courses:
        tracked_courses = [
            str(x.get("course"))
            for x in state.get("items", [])
            if isinstance(x, Mapping)
        ]
    rows = iter_questions(
        root, tracked_courses, include_untracked=bool(state.get("include_untracked"))
    )
    if state_kind == "visual":
        rows = [row for row in rows if row["risk_tier"] != "low"]
    manifest_default = 8 if state_kind == "visual" else 50
    current = _manifest(
        rows, pass_id, int(state.get("batch_size") or batch_size or manifest_default)
    )
    validate_queue_state(state, rows)
    if current["queue_hash"] != state.get("queue_hash"):
        raise RuntimeError("source questions changed; run --init again before resuming")
    size = int(
        batch_size or state.get("batch_size") or (50 if state_kind != "visual" else 8)
    )
    start = int(state.get("next_index") or 0)
    if start >= len(rows):
        state["status"] = "complete"
        _atomic_json(state_path, state)
        return state
    batch_rows = rows[start : start + size]
    emitted_uids = {
        str(uid)
        for batch in state.get("batches") or []
        if isinstance(batch, Mapping)
        for uid in batch.get("source_uids") or []
    }
    if any(row["source_uid"] in emitted_uids for row in batch_rows):
        raise ValueError("resume would emit an already emitted source_uid")
    number = len(state.get("batches") or []) + 1
    name = f"batch-{number:04d}.json"
    if state_kind in {"blind", "both"}:
        blind = _batch_packet(
            "blind-solution-batch",
            pass_id,
            name[:-5],
            [make_blind_packet(row, pass_id) for row in batch_rows],
        )
        validate_batch(blind, {row["source_uid"]: row["source_hash"] for row in rows})
        _atomic_json(output_dir / "blind" / pass_id / name, blind)
    if state_kind == "visual":
        visual = _batch_packet(
            "visual-audit-batch",
            pass_id,
            name[:-5],
            [make_visual_packet(row, pass_id) for row in batch_rows],
        )
        validate_batch(visual, {row["source_uid"]: row["source_hash"] for row in rows})
        _atomic_json(output_dir / "visual" / pass_id / name, visual)
    elif state_kind == "both":
        all_visual = [
            row
            for row in iter_questions(
                root,
                tracked_courses,
                include_untracked=bool(state.get("include_untracked")),
            )
            if row["risk_tier"] != "low"
        ]
        visual_start = int(state.get("visual_next_index") or 0)
        visual_size = int(state.get("visual_batch_size") or 8)
        visual_rows = all_visual[visual_start : visual_start + visual_size]
        if visual_rows:
            visual_emitted_uids = {
                str(uid)
                for batch in state.get("visual_batches") or []
                if isinstance(batch, Mapping)
                for uid in batch.get("source_uids") or []
            }
            if any(row["source_uid"] in visual_emitted_uids for row in visual_rows):
                raise ValueError(
                    "resume would emit an already emitted visual source_uid"
                )
            visual = _batch_packet(
                "visual-audit-batch",
                pass_id,
                name[:-5],
                [make_visual_packet(row, pass_id) for row in visual_rows],
            )
            validate_batch(
                visual, {row["source_uid"]: row["source_hash"] for row in rows}
            )
            _atomic_json(output_dir / "visual" / pass_id / name, visual)
            state["visual_next_index"] = visual_start + len(visual_rows)
            state.setdefault("visual_batches", []).append(
                {
                    "batch_id": name[:-5],
                    "source_uids": [row["source_uid"] for row in visual_rows],
                }
            )
    state["next_index"] = start + len(batch_rows)
    state["status"] = "complete" if state["next_index"] >= len(rows) else "running"
    state["kind"] = state_kind
    state.setdefault("batches", []).append(
        {
            "batch_id": name[:-5],
            "start": start,
            "count": len(batch_rows),
            "source_uids": [row["source_uid"] for row in batch_rows],
        }
    )
    _atomic_json(state_path, state)
    return state


def list_queue(
    *, output_dir: Path = DEFAULT_OUTPUT, pass_id: str | None = None
) -> list[dict[str, Any]]:
    paths = (
        [output_dir / f"state-{pass_id}.json"]
        if pass_id
        else sorted(output_dir.glob("state-*.json"))
    )
    return [value for path in paths if isinstance((value := _read(path, None)), dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true")
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--list", action="store_true")
    parser.add_argument("--course", action="append", choices=COURSES)
    parser.add_argument("--pass-id", default="pass-1")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--kind", choices=("blind", "visual", "both"), default=None)
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="显式将未在 quality-ledger 中匹配的发布题目加入队列",
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.init:
        state = initialize(
            root=args.root,
            output_dir=args.output_dir,
            courses=args.course or COURSES,
            pass_id=args.pass_id,
            batch_size=args.batch_size,
            kind=args.kind or "both",
            include_untracked=args.include_untracked,
        )
        print(
            json.dumps(
                {
                    "pass_id": state["pass_id"],
                    "total": len(state["items"]),
                    "status": state["status"],
                },
                ensure_ascii=False,
            )
        )
    elif args.resume:
        state = resume(
            root=args.root,
            output_dir=args.output_dir,
            pass_id=args.pass_id,
            batch_size=args.batch_size,
            kind=args.kind,
        )
        print(
            json.dumps(
                {
                    "pass_id": state["pass_id"],
                    "next_index": state["next_index"],
                    "status": state["status"],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(
            json.dumps(
                list_queue(output_dir=args.output_dir, pass_id=args.pass_id),
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
