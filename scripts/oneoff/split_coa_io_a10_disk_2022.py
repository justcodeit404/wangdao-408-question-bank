#!/usr/bin/env python3
"""coa I/O方式 A10 拆条：截断 A10 粘尾 + 补录 2022 磁盘 DMA 题为 A11。

证据：data/patches/split_coa_io_a10_disk_2022.json（27 王道计组 7.3.4 原书核对）
幂等：A10 已截断 / A11 已存在则分别跳过。改完需跑 scripts/rebuild_bank.ps1。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "data/patches/split_coa_io_a10_disk_2022.json"
TARGET = ROOT / "output/questions_coa.json"


def main() -> None:
    patch = json.loads(PATCH.read_text(encoding="utf-8"))
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    changed = False
    for op in patch["operations"]:
        ch_name = op["chapter_name"]
        ch = next((c for c in data["chapters"] if c.get("name") == ch_name), None)
        if ch is None:
            raise SystemExit(f"chapter not found: {ch_name}")
        if op["op"] == "truncate_content":
            q = next((x for x in ch["questions"] if x.get("id") == op["qid"]), None)
            if q is None:
                raise SystemExit(f"question not found: {ch_name}::{op['qid']}")
            keep = op["keep_through"]
            if keep in q["content"]:
                q["content"] = q["content"][: q["content"].find(keep) + len(keep)]
                print(f"  [truncate] {ch_name}::{op['qid']}")
                changed = True
            else:
                print(f"  [skip] {ch_name}::{op['qid']} already truncated")
        elif op["op"] == "add_question":
            spec = op["question"]
            ids = {x.get("id") for x in ch["questions"]}
            if spec["id"] in ids:
                print(f"  [skip] {ch_name}::{spec['id']} already present")
                continue
            a10 = next((x for x in ch["questions"] if x.get("id") == op["insert_after_id"]), None)
            topic = a10.get("topic_title") if a10 else None
            q = {
                "id": spec["id"],
                "type": spec["type"],
                "content": spec["content_prefix"] + spec["content_tail_from_a10"],
                "options": None,
                "sub_questions": None,
                "page": spec["page"],
                "bbox": [110.0, 260.0, 975.0, 780.0],
                "has_image": spec["has_image"],
                "image_ref": None,
                "topic_title": topic,
                "answer": {"choice": None, "explanation": spec["answer_explanation"]},
                "q_pages": spec["q_pages"],
                "a_pages": spec["a_pages"],
            }
            at = len(ch["questions"])
            if a10 is not None:
                at = ch["questions"].index(a10) + 1
            ch["questions"].insert(at, q)
            ch["question_count"] = len(ch["questions"])
            print(f"  [add] {ch_name}::{spec['id']} at index {at}")
            changed = True
        else:
            raise SystemExit(f"unknown op: {op['op']}")
    data["total_questions"] = sum(len(c.get("questions") or []) for c in data["chapters"])
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"total_questions={data['total_questions']} changed={changed}")
    if changed:
        print("Next: powershell -File scripts/rebuild_bank.ps1")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
