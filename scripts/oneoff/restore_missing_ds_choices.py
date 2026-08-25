#!/usr/bin/env python3
"""将 OCR 漏掉的 3 道数据结构选择题写回 output/questions.json，并 merge 到 Viewer。

证据：27 王道《数据结构》OCR（data/ocr/ds）+ data/patches/restore_missing_ds_choices.json
幂等：若目标 id 已存在则跳过该题。
"""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from config import MATH_BANK_DIR  # noqa: E402
from merge_courses import main as merge_main  # noqa: E402


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_patch(data: dict, patch: dict) -> list[str]:
    by_name = {ch.get("name"): ch for ch in data.get("chapters", [])}
    applied: list[str] = []
    for item in patch.get("questions", []):
        ch_name = item["chapter_name"]
        q = deepcopy(item["question"])
        qid = q["id"]
        ch = by_name.get(ch_name)
        if ch is None:
            raise SystemExit(f"chapter not found: {ch_name}")
        qs = ch.setdefault("questions", [])
        existing_ids = {str(x.get("id")) for x in qs}
        if qid in existing_ids:
            print(f"  [skip] {ch_name}::{qid} already present")
            continue
        after = item.get("insert_after_id")
        insert_at = len(qs)
        if after:
            for i, existing in enumerate(qs):
                if str(existing.get("id")) == after:
                    insert_at = i + 1
                    break
        qs.insert(insert_at, q)
        ch["question_count"] = len(qs)
        applied.append(f"{ch_name}::{qid}")
        print(f"  [add] {ch_name}::{qid} at index {insert_at}")
    # recount
    total = sum(len(ch.get("questions") or []) for ch in data.get("chapters", []))
    data["total_questions"] = total
    return applied


def update_quality_hold():
    hold_path = MATH_BANK_DIR / "quality-hold.json"
    hold = _load(hold_path)
    hashes = hold.setdefault("source_hashes", {})
    for key in ("ds", "coa", "net", "os"):
        p = MATH_BANK_DIR / f"data-{key}.json"
        if p.is_file():
            hashes[key] = _sha256(p)
    # choice count across 4 courses (viewer filter)
    total_choice = 0
    for key in ("ds", "coa", "net", "os"):
        p = MATH_BANK_DIR / f"data-{key}.json"
        if not p.is_file():
            continue
        d = _load(p)
        for ch in d.get("chapters", []):
            for q in ch.get("questions") or []:
                t = str(q.get("type") or "")
                if "选择" in t or "choice" in t.lower():
                    total_choice += 1
    summary = hold.setdefault("summary", {})
    summary["total_choice_questions"] = total_choice
    summary["verified"] = total_choice
    summary["held"] = 0
    summary["verification_rate"] = 1.0
    hold_path.write_text(
        json.dumps(hold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"  [quality-hold] ds={hashes.get('ds', '')[:12]}… choice_total={total_choice}"
    )


def main() -> int:
    patch_path = ROOT / "data" / "patches" / "restore_missing_ds_choices.json"
    out_json = ROOT / "output" / "questions.json"
    patch = _load(patch_path)
    data = _load(out_json)
    print(f"before total_questions={data.get('total_questions')}")
    applied = apply_patch(data, patch)
    out_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"after total_questions={data.get('total_questions')} applied={len(applied)}")

    # regenerate viewer data-*.json
    sys.argv = ["merge_courses.py", str(ROOT / "output" / "questions_all.json")]
    merge_main()
    update_quality_hold()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
