#!/usr/bin/env python3
"""全库 OCR 病征模式扫描。

扫描 math-bank/data-*.json 中的选择题，输出命中高频 OCR 病征的题目列表，
供人工核对原书后写入 page_review_patches.json。

用法：
  python scripts/scan_patterns.py
  python scripts/scan_patterns.py --course ds
  python scripts/scan_patterns.py --json
  python scripts/scan_patterns.py --summary   # 只按病征汇总计数
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BANK = PROJECT_ROOT / "math-bank"
COURSES = ("ds", "coa", "net", "os")

# 病征：名称 -> (正则, 说明)
# 注：只保留高置信、低误报的模式；中文全角（）、α 装填因子等合法用法勿入。
PATTERNS = {
    "roman_ii_dup": (
        re.compile(r"(?:^|\n|。|\s)III\.[^\n]{0,40}\n\s*III\."),
        "罗马编号 III 重复出现",
    ),
    "roman_il": (
        re.compile(r"\bIl\.|\bIll\.|\bIIIl"),
        "罗马编号 I/l 混淆",
    ),
    "o_zero": (
        re.compile(
            r"\b(Po|Netl|BOH|COH|filel|readO|write0|threadl|sinI|lus|waitO|FO00)\b"
            r"|\bOx[0-9A-Fa-f]{1,8}\b"
        ),
        "O/0 或 l/1 混淆",
    ),
    "superscript_flat": (
        re.compile(
            r"(?<!\^)\b\d{1,4}[x×]\d{1,2}(?!\^)(?!\d)(?![x×位Bbit像素])"
            r"|\bO\(n2\)|\bn\?-e\b"
        ),
        "疑似上标丢失（排除 1024x8位/像素 等合法记法）",
    ),
    "ellipsis_comma": (
        re.compile(r'",|"…'),
        '省略号被 OCR 成 ",',
    ),
    "option_leak": (
        re.compile(r"丢失$|如图所示.*拓扑|^\d+\.\s*[A-Z].{0,80}$"),
        "选项/题干混入后续题号",
    ),
    "cn_one_sep": (
        re.compile(r"一I/O|一I总线"),
        "连接符 一 疑似 —",
    ),
    "muus": (
        re.compile(r"μus"),
        "μus 应为 μs",
    ),
    "dup_option_letter": (
        re.compile(r"^[A-D]\.[^\n]{0,80}\n\s*[A-D]\."),
        "选项行疑似串题重复",
    ),
}


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
                hits.append(
                    {
                        "course": course,
                        "chapter": ch.get("name"),
                        "qid": q.get("id"),
                        "page": q.get("page"),
                        "matches": found,
                        "content": (q.get("content") or "")[:120].replace("\n", " / "),
                    }
                )
    return hits


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--course", choices=COURSES)
    p.add_argument("--json", action="store_true")
    p.add_argument("--summary", action="store_true")
    args = p.parse_args()

    courses = (args.course,) if args.course else COURSES
    all_hits: list[dict] = []
    for c in courses:
        all_hits.extend(scan_course(c))

    if args.json:
        print(json.dumps(all_hits, ensure_ascii=False, indent=2))
        return

    if args.summary:
        counter: Counter[str] = Counter()
        for h in all_hits:
            for name, _desc, _frag in h["matches"]:
                counter[name] += 1
        print(f"扫描选择题命中 {len(all_hits)} 题")
        for name, n in counter.most_common():
            print(f"  {name}: {n}")
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
