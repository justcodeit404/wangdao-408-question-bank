"""把本地读图转录结果对照题库，写成与视觉门禁相同的 records/patches。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from vision_quality_gate import (  # noqa: E402
    HOLD_PATH,
    MANIFEST_PATH,
    PASS_STATUSES,
    PATCH_PATH,
    STATE_PATH,
    _append_regressions,
    _load_json,
    _load_patches,
    _load_state,
    _same_field,
    _write_hold,
    apply_patch_to_question,
    apply_patches,
    audit_bank_after_round,
    build_manifest,
    canonical_choice,
    refresh_verified_for_patches,
    source_hash,
    summarize_round,
)
from utils import write_json_atomic


def _decision_from_transcript(item: dict, transcript: dict) -> dict:
    uid = item["source_uid"]
    if not transcript.get("readable"):
        return {
            "source_uid": uid,
            "course_key": item["course_key"],
            "chapter": item["chapter"],
            "question_id": item["question_id"],
            "source_hash": item["source_hash"],
            "status": "held",
            "selection": "rotation",
            "reason": transcript.get("reason") or "原书裁图看不清",
        }
    fields = transcript.get("fields") or {}
    content = fields.get("content")
    options = fields.get("options")
    choice = canonical_choice(fields.get("answer.choice") or fields.get("answer_choice"))
    explanation = fields.get("explanation")
    if not choice:
        return {
            "source_uid": uid,
            "course_key": item["course_key"],
            "chapter": item["chapter"],
            "question_id": item["question_id"],
            "source_hash": item["source_hash"],
            "status": "held",
            "selection": "rotation",
            "reason": "未从原书读出答案",
        }
    bank = item.get("bank") or {}
    consensus = {
        "content": content,
        "options": options,
        "answer.choice": choice,
        "explanation": explanation,
    }
    if bool(transcript.get("requires_image")) != bool(item.get("has_image")):
        return {
            "source_uid": uid,
            "course_key": item["course_key"],
            "chapter": item["chapter"],
            "question_id": item["question_id"],
            "source_hash": item["source_hash"],
            "status": "held",
            "selection": "rotation",
            "reason": "原书配图与题库配图状态不一致",
            "fields": consensus,
        }
    patch: dict = {}
    if not _same_field(content, bank.get("content"), "content"):
        patch["content"] = content
    if options and not _same_field(options, bank.get("options"), "options"):
        patch["options"] = options
    if not _same_field(choice, bank.get("answer.choice"), "answer.choice"):
        patch.setdefault("answer", {})["choice"] = choice
    if explanation and not _same_field(explanation, bank.get("explanation"), "explanation"):
        patch.setdefault("answer", {})["explanation"] = explanation
    status = "auto_fixed" if patch else "verified"
    return {
        "source_uid": uid,
        "course_key": item["course_key"],
        "chapter": item["chapter"],
        "question_id": item["question_id"],
        "source_hash": item["source_hash"],
        "status": status,
        "selection": "rotation",
        "models": ["claude-local-vision"],
        "fields": consensus,
        "patch": patch or None,
    }


def ingest(worklist_path: Path, transcript_paths: list[Path], round_id: str) -> dict:
    worklist = json.loads(worklist_path.read_text(encoding="utf-8"))
    by_uid = {item["source_uid"]: item for item in worklist["items"]}
    transcripts: dict[str, dict] = {}
    for path in transcript_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("transcripts") or payload.get("decisions") or payload.get("items") or []
        for row in rows:
            if isinstance(row, dict) and row.get("source_uid"):
                transcripts[row["source_uid"]] = row
    records = []
    missing = []
    for item in worklist["items"]:
        uid = item["source_uid"]
        if uid not in transcripts:
            missing.append(uid)
            records.append({
                "source_uid": uid,
                "course_key": item["course_key"],
                "chapter": item["chapter"],
                "question_id": item["question_id"],
                "source_hash": item["source_hash"],
                "status": "held",
                "selection": "rotation",
                "reason": "本地读图未返回该题",
            })
            continue
        records.append(_decision_from_transcript(item, transcripts[uid]))
    state = _load_state()
    state["round_id"] = round_id
    refresh_verified_for_patches(state)
    fixed = []
    held = set()
    for record, item in zip(records, worklist["items"]):
        if record["status"] == "held":
            held.add(record["source_uid"])
            continue
        patch = record.get("patch")
        if patch:
            fixed.append({**record, "patch": patch})
        question = {
            "content": item["bank"].get("content"),
            "options": item["bank"].get("options"),
            "answer": {
                "choice": item["bank"].get("answer.choice"),
                "explanation": item["bank"].get("explanation"),
            },
        }
        state.setdefault("verified", {})[record["source_uid"]] = source_hash(apply_patch_to_question(question, patch))
    if fixed:
        patches = _load_patches()
        items = patches.setdefault("items", [])
        for item in fixed:
            items[:] = [old for old in items if not (old.get("source_uid") == item["source_uid"] and old.get("source_hash") == item["source_hash"])]
            items.append(item)
        PATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(PATCH_PATH, patches, indent=2, ensure_ascii=False)
        _append_regressions(fixed)
        apply_patches()
    if held:
        _write_hold(held, "local_vision_conflict")
    summary = build_manifest(records, state, "", ("claude-local-vision",), "local")["summary"]
    history = [row for row in state.get("round_history", []) if row.get("round_id") != round_id]
    history.append({"round_id": round_id, "sample_accuracy": summary["sample_accuracy"], "sample_passed": summary["sample_passed"], "sample_total": summary["sample_total"], "accuracy": summary["accuracy"], "total": summary["total"]})
    state["round_history"] = history
    state["last_records"] = records
    write_json_atomic(STATE_PATH, state, indent=2, ensure_ascii=False)
    status = "verified" if not any(record["status"] == "held" for record in records) else "verified_with_holds"
    manifest = build_manifest(records, state, status, ("claude-local-vision",), "local")
    write_json_atomic(MANIFEST_PATH, manifest, indent=2, ensure_ascii=False)
    digest = summarize_round(records)
    audit = None
    if (summary.get("sample_accuracy") or 0) <= 0.9:
        audit = audit_bank_after_round(records)
    return {"summary": summary, "error_summary": digest, "bank_audit": audit, "missing": missing}


if __name__ == "__main__":
    worklist = Path(sys.argv[1])
    transcripts = [Path(p) for p in sys.argv[2:]]
    result = ingest(worklist, transcripts, worklist.parent.name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
