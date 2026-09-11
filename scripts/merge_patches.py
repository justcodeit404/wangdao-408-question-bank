#!/usr/bin/env python3
"""合并 page_review_patches.json 中重复的 (course, chapter, qid) 补丁。

后出现的 fields 会覆盖同名字段；options 会逐键合并。

用法：
  python scripts/merge_patches.py           # 就地合并
  python scripts/merge_patches.py --dry-run # 只报告不写入
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PATCH_PATH = Path(__file__).resolve().parent.parent / "data" / "quality" / "page_review_patches.json"
VALID_FIELDS = {"content", "options", "choice", "explanation"}


def merge_items(items: list) -> tuple[list, int]:
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for it in items:
        key = (
            str(it.get("course") or "").strip(),
            str(it.get("chapter") or "").strip(),
            str(it.get("qid") or "").strip(),
        )
        fields = dict(it.get("fields") or {})
        # 过滤未知字段
        fields = {k: v for k, v in fields.items() if k in VALID_FIELDS}
        if not fields:
            continue
        if key in merged:
            old = merged[key]
            for k, v in fields.items():
                if k == "options" and isinstance(v, dict) and isinstance(old.get("options"), dict):
                    old["options"].update(v)
                else:
                    old[k] = v
        else:
            merged[key] = fields
            order.append(key)
    out = [
        {"course": c, "chapter": ch, "qid": q, "fields": merged[(c, ch, q)]}
        for (c, ch, q) in order
    ]
    return out, len(items) - len(out)


def main():
    dry = "--dry-run" in sys.argv
    payload = json.loads(PATCH_PATH.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    new_items, removed = merge_items(items)
    print(f"原始 {len(items)} → 合并后 {len(new_items)}（去除重复 {removed}）")
    if dry:
        return
    payload["items"] = new_items
    PATCH_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写回 {PATCH_PATH}")


if __name__ == "__main__":
    main()
