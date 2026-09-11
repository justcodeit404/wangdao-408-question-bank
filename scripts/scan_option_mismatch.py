#!/usr/bin/env python3
"""扫描疑似选项/题干串题或选项与题干主题不匹配的选择题。

启发式：
1. 题干问端口/协议/层，选项却是比特串或时间/速率
2. 选项含图注词（图中/主机/路由器/时间/交换机等）
3. 题干有图但选项看起来像另一题
4. 选项 D 前缀与 A-C 风格明显不同（数字串 vs 中文）

用法：
  python scripts/scan_option_mismatch.py
  python scripts/scan_option_mismatch.py --json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BANK = Path(__file__).resolve().parent.parent / "math-bank"
COURSES = ("ds", "coa", "net", "os")

FIG_NOISE = re.compile(r"图中[:：]|如图所示|网关|ack_seq|丢失$|H1 H2|时间$")
BITSTR = re.compile(r"^[01\s]{6,}$")
RATE = re.compile(r"\d+(\.\d+)?\s*(Mb/s|GB/s|ms|ns|μs)")

# 题干关键词 → 选项应包含的关键词集合（任一即可）
STEM_OPT = [
    (re.compile(r"端口号|端口"), re.compile(r"端口|源|目的|长度|检验"), "问端口"),
    (re.compile(r"全双工|半双工"), re.compile(r"以太网|双工|光纤|Base"), "问双工"),
    (re.compile(r"UDP实现分用|分用时所依据"), re.compile(r"端口"), "问分用字段"),
]


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
            content = q.get("content") or ""
            opts = q.get("options") or {}
            opt_text = " ".join(str(opts.get(k) or "") for k in "ABCD")
            reasons = []

            for stem_rx, opt_rx, label in STEM_OPT:
                if stem_rx.search(content) and not opt_rx.search(opt_text):
                    reasons.append(f"主题不匹配:{label}")

            if FIG_NOISE.search(opt_text):
                reasons.append("选项含图注词")

            for k, v in opts.items():
                if BITSTR.match(str(v).replace(" ", "")):
                    reasons.append(f"选项{k}为比特串")

            # 题干问时间/速率，选项全是比特串
            if re.search(r"时间|速率", content) and all(
                BITSTR.match(str(opts.get(k) or "").replace(" ", "")) for k in opts
            ):
                reasons.append("题干时间/速率但选项全比特串")

            if reasons:
                hits.append({
                    "course": course,
                    "chapter": ch.get("name"),
                    "qid": q.get("id"),
                    "page": q.get("page"),
                    "reasons": reasons,
                    "content": content[:100].replace("\n", " / "),
                    "options": opts,
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

    print(f"疑似串题/主题不匹配 {len(all_hits)} 题")
    for h in all_hits:
        print("=" * 72)
        print(f"{h['course']}|{h['chapter']}|{h['qid']}|p{h['page']}")
        print("  原因:", "; ".join(h["reasons"]))
        print("  C:", h["content"])
        print("  O:", h["options"])


if __name__ == "__main__":
    main()
