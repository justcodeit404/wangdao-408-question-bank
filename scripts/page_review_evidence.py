#!/usr/bin/env python3
"""Persist original-page review evidence without storing page binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from config import PROJECT_ROOT

DEFAULT_INPUT = PROJECT_ROOT.parents[1] / "temp" / "page-review" / "reviews.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "quality" / "page_review_evidence.json"
DEFAULT_QUEUE = PROJECT_ROOT.parents[1] / "temp" / "page-review" / "queue.json"
DEFAULT_PATCHES = PROJECT_ROOT / "data" / "quality" / "page_review_patches.json"
PROTOCOL = "codex-original-page-review-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_page(value: Any) -> tuple[str, str, bool]:
    raw = str(value or "").strip()
    if not raw:
        return "", "", False
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT.parents[1] / raw
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    exists = resolved.is_file()
    return raw.replace("\\", "/"), _sha256(resolved) if exists else "", exists


def _page_list(row: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = row.get(key) or []
    if not isinstance(values, list) or not values:
        raise ValueError(f"review {row.get('source_uid')} missing {key}")
    pages: list[dict[str, Any]] = []
    for value in values:
        path_value = value.get("path") if isinstance(value, dict) else value
        path, sha, exists = _resolve_page(path_value)
        if not exists:
            raise ValueError(f"review {row.get('source_uid')} page missing: {path_value}")
        page = {"path": path, "sha256": sha}
        if isinstance(value, dict) and value.get("page") is not None:
            page["page"] = int(value["page"])
        pages.append(page)
    return pages


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    uid = str(row.get("source_uid") or "").strip()
    action = str(row.get("final_action") or "").strip().lower()
    if not uid or action not in {"certify", "patch", "hold"}:
        raise ValueError(f"invalid review row: {uid or '<missing uid>'}")
    protocol = str(row.get("protocol") or PROTOCOL).strip()
    if protocol != PROTOCOL:
        raise ValueError(f"unsupported review protocol for {uid}: {protocol}")
    normalized = {
        "source_uid": uid,
        "protocol": protocol,
        "reviewer": str(row.get("reviewer") or "codex-vision"),
        "reviewed_at": str(row.get("reviewed_at") or datetime.now(timezone.utc).isoformat()),
        "q_pages_viewed": _page_list(row, "q_pages_viewed"),
        "a_pages_viewed": _page_list(row, "a_pages_viewed"),
        "final_action": action,
        "content_match": row.get("content_match"),
        "options_match": row.get("options_match"),
        "answer_match": row.get("answer_match"),
        "explanation_match": row.get("explanation_match"),
        "image_match": row.get("image_match"),
        "detected_errors": list(row.get("detected_errors") or []),
        "rationale": str(row.get("rationale") or "").strip(),
    }
    if row.get("post_patch_verified") is not None:
        normalized["post_patch_verified"] = bool(row["post_patch_verified"])
    if row.get("source_hash"):
        normalized["source_hash"] = str(row["source_hash"])
    if row.get("crop_sha256"):
        normalized["crop_sha256"] = str(row["crop_sha256"])
    return normalized


def load_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid review JSONL {path}:{line_no}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"review row is not an object {path}:{line_no}")
            rows.append(normalize_row(value))
    return rows


def build_evidence(rows: Iterable[dict[str, Any]], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = previous.get("records", []) if isinstance(previous, dict) else []
    by_key = {
        (str(row.get("source_uid")), str(row.get("reviewed_at")), str(row.get("final_action"))): dict(row)
        for row in existing if isinstance(row, dict)
    }
    for row in rows:
        key = (row["source_uid"], row["reviewed_at"], row["final_action"])
        # 同一审核记录可能在补丁后 source_hash 更新；新记录必须替换旧快照，
        # 不能因去重而继续保留过期哈希。
        by_key[key] = dict(row)
    records = list(by_key.values())
    records.sort(key=lambda row: (str(row.get("source_uid")), str(row.get("reviewed_at"))))
    return {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }


def _manifest_rows(queue_path: Path, patches_path: Path) -> list[dict[str, Any]]:
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.is_file() else {}
    patches = json.loads(patches_path.read_text(encoding="utf-8")) if patches_path.is_file() else {}
    queue_by_uid = {
        str(row.get("source_uid")): row
        for row in queue.get("items", [])
        if isinstance(row, dict) and row.get("source_uid")
    }
    rows: list[dict[str, Any]] = []
    for patch in patches.get("items", []) if isinstance(patches, dict) else []:
        if not isinstance(patch, dict):
            continue
        course = str(patch.get("course") or "").strip()
        chapter = str(patch.get("chapter") or "").strip()
        qid = str(patch.get("qid") or "").strip()
        uid = f"408:cs408-{course}::{chapter}::{qid}"
        queue_row = queue_by_uid.get(uid)
        if not queue_row:
            continue
        rows.append({
            "source_uid": uid,
            "source_hash": queue_row.get("source_hash"),
            "q_pages_viewed": queue_row.get("q_view") or [],
            "a_pages_viewed": queue_row.get("a_view") or [],
            "final_action": "patch",
            "detected_errors": ["persisted_page_review_patch"],
            "rationale": "migrated from page_review_patches.json; patch was reported as post-patch rechecked",
            "post_patch_verified": True,
            "reviewed_at": queue_row.get("last_reviewed_at") or "migrated:page_review_patches.json",
            "reviewer": "codex-vision",
        })
    return rows


def sync(
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    queue_path: Path = DEFAULT_QUEUE,
    patches_path: Path = DEFAULT_PATCHES,
) -> dict[str, int]:
    previous: dict[str, Any] = {}
    if output_path.is_file():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
    rows = load_jsonl([input_path])
    rows.extend(normalize_row(row) for row in _manifest_rows(queue_path, patches_path))
    packet = build_evidence(rows, previous)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"records": len(packet["records"]), "new": len(packet["records"]) - len(previous.get("records", []))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--patches", type=Path, default=DEFAULT_PATCHES)
    args = parser.parse_args()
    print(json.dumps(sync(args.input, args.output, args.queue, args.patches), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
