#!/usr/bin/env python3
"""全库 OCR 病征模式扫描。

扫描 math-bank/data-*.json 中的选择题，输出命中高频 OCR 病征的题目列表，
供人工核对原书后写入 page_review_patches.json。

用法：
  python scripts/scan_patterns.py
  python scripts/scan_patterns.py --course ds
  python scripts/scan_patterns.py --json  # 输出 JSON 便于脚本处理
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BANK = PROJECT_ROOT / "math-bank"
COURSES = ("ds", "coa", "net", "os")

# 病征：名称 -> (正则, 说明)
# 注：只保留高置信、低误报的模式
PATTERNS = {
    "roman_ii_dup": (re.compile(r"(?:^|\n|。|\s)III\.[^\n]{0,40}\n\s*III\."), "罗马编号 III 重复出现"),
    "roman_il": (re.compile(r"\bIl\.|\bIll\.|\bIIIl"), "罗马编号 I/l 混淆"),
    "o_zero": (re.compile(r"\b(Po|Netl|BOH|COH|Ox[0-9A-Fa-f]|filel|readO|write0|threadl|sinI|lus|waitO)\b"), "O/0 或 l/1 混淆"),
    "superscript_flat": (re.compile(r"(?<!\^)\b\d{1,4}[x×]\d{1,2}(?!\^)(?!\d)|\b2[0-9]{1,3}页\b|\bO\(n2\)|\bn\?-e\b"), "疑似上标丢失"),
    "option_leak": (re.compile(r"②③|图中[:：]|如图所示.*拓扑|H1 H2|ack_seq|丢失$"), "选项/题干混入图注或后续题号"),
    "cn_one_sep": (re.compile(r"一I/O|一I总线"), "连接符 一 疑似 —"),
    "muus": (re.compile(r"μus"), "μus 应为 μs"),
}

# 已知可忽略（全库合法）的排除
IGNORE_RES = [
    re.compile(r"^[0-9a-zA-Z]+$"),  # 纯字母数字
]


def _text(q: dict) -> str:
    opts = q.get("options") or {}
    parts = [q.get("content") or ""]
    for k in ("A", "B", "C", "D"):
        parts.append(str(opts.get(k) or ""))
    ans = q.get("answer") or {}
    parts.append(str(ans.get("explanation") or ""))
    return "\n".join(parts)


def scan_course(course: str) -> list[dict]:
    path = BANK / f"data-{course}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    hits = []
    for ch in data.get("chapters") or []:
        for q in ch.get("questions") or []:
            if q.get("type") != "选择题":
                continue
            text = _text(q)
            found = []
            for name, (rx, desc) in PATTERNS.items():
                m = rx.search(text)
                if m:
                    found.append((name, desc, m.group(0)[:60]))
            if found:
                hits.append({
                    "course": course,
                    "chapter": ch.get("name"),
                    "qid": q.get("id"),
                    "page": q.get("page"),
                    "matches": found,
                    "content": (q.get("content") or "")[:120].replace("\n", " / "),
                })
    return hits


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--course", choices=COURSES)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    courses = (args.course,) if args.course else COURSES
    all_hits = []
    for c in courses:
        all_hits.extend(scan_course(c))

    if args.json:
        print(json.dumps(all_hits, ensure_ascii=False, indent=2))
        return

    print(f"扫描选择题命中 {len(all_hits)} 题")
    for h in all_hits:
        print("=" * 72)
        print(f"{h['course']}|{h['chapter']}|{h['qid']}|p{h['page']}")
        for name, desc, frag in h["matches"]:
            print(f"  [{name}] {desc}: {frag!r}")
        print("C:", h["content"])


if __name__ == "__main__":
    main()
