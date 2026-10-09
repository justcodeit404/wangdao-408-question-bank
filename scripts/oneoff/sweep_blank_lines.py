#!/usr/bin/env python3
"""全库题干空行清扫：content 中 \\n\\n+ 收为 \\n，表格行相邻空行保留。

输出 patch 条目写入 page_review_patches.json（同 key 后出现者覆盖，merge_patches 语义）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT / "data" / "quality" / "page_review_patches.json"


def collapse(content: str) -> str:
    lines = content.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        if line == "":
            prev = out[-1] if out else ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if prev.startswith("|") or nxt.startswith("|"):
                if out and out[-1] == "":
                    continue  # 表格旁多个空行收一个
                out.append(line)
                continue
            continue  # 非表格空行直接删除
        out.append(line)
    return "\n".join(out)


def main() -> None:
    payload = json.loads(PATCH_PATH.read_text(encoding="utf-8"))
    existing = {
        (it["course"], it["chapter"], it["qid"]) for it in payload["items"]
    }
    added, touched = 0, 0
    for key in ("ds", "coa", "os", "net"):
        bank = json.loads((ROOT / "math-bank" / f"data-{key}.json").read_text(encoding="utf-8"))
        for ch in bank["chapters"]:
            for q in ch["questions"]:
                c = q.get("content") or ""
                if "\n\n" not in c:
                    continue
                new = collapse(c)
                if new == c:
                    continue
                touched += 1
                k = (key, ch["name"], q["id"])
                if k in existing:
                    # 已有该题补丁：直接更新其中 content，避免条目膨胀
                    for it in payload["items"]:
                        if (it["course"], it["chapter"], it["qid"]) == k and "content" in it["fields"]:
                            it["fields"]["content"] = new
                            break
                    else:
                        payload["items"].append(
                            {"course": k[0], "chapter": k[1], "qid": k[2], "fields": {"content": new}}
                        )
                        added += 1
                else:
                    payload["items"].append(
                        {"course": k[0], "chapter": k[1], "qid": k[2], "fields": {"content": new}}
                    )
                    existing.add(k)
                    added += 1
    PATCH_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"清扫题干 {touched} 题（新增补丁 {added}，其余并入已有补丁）")


if __name__ == "__main__":
    main()
