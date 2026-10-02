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

# 只打在解析字段上的病征：解答题也要扫（串正文/串下题主要发生在解析里）。
EXPL_PATTERNS = {
    "expl_bleed": (
        re.compile(r"考点追踪|本节是|【解析】|答案与解析"),
        "解析串入教材正文/下一题解析",
    ),
}

# 全题型（含解答题）都打的病征，打在 content+options+explanation 全文上。
ALL_PATTERNS = {
    "reg_l1_o0": (
        re.compile(
            r"\bR[lI][a-z]+out\b"
            r"|\((?:R[lIiOo])\)"
            r"|(?<![A-Za-z0-9])R[lI](?![A-Za-z0-9])"
            r"|(?<![A-Za-z0-9])RO(?![A-Za-z0-9])"
        ),
        "寄存器名 l/1、O/0 混淆（R1out/(R1)/(R0) 类）",
    ),
    "dot_in_digits": (
        re.compile(r"\d·\d|·[01]{2,}|[01]{2,}·"),
        "数字/二进制串中的 ·（省略号/点号压扁嫌疑）",
    ),
    "degree_prime": (
        re.compile(r"\d°|\d'(?!\d)"),
        "数字后的 °/' 疑上标压扁",
    ),
    "latex_shell": (
        re.compile(r"\$[^$\n]{1,60}\$"),
        "LaTeX 壳残留",
    ),
    "zero_sign_nosub": (
        re.compile(r"\[[-+]0\]=(?![原反补移])"),
        "±0 机器数疑丢「原/反/补/移」下标",
    ),
    "ellipsis_junk": (
        re.compile(r"、\.|,,|;;|ffx|\d{3,},{2,}"),
        "省略号/分隔符烂码（.,、ffx 类）",
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
            text = _text(q)
            found = []
            expl = str((q.get("answer") or {}).get("explanation") or "")
            for name, (rx, desc) in EXPL_PATTERNS.items():
                m = rx.search(expl)
                if m:
                    found.append((name, desc, m.group(0)[:60]))
            if q.get("type") == "选择题":
                for name, (rx, desc) in PATTERNS.items():
                    m = rx.search(text)
                    if m:
                        found.append((name, desc, m.group(0)[:60]))
            for name, (rx, desc) in ALL_PATTERNS.items():
                m = rx.search(text)
                if m:
                    found.append((name, desc, m.group(0)[:60]))
            # 自定义检查：解析截断嫌疑 / 题干未闭合括号
            body_lines = [
                l
                for l in expl.split("\n")
                if l.strip() and not l.strip().startswith("答案图片")
            ]
            img_lines = expl.count("答案图片：")
            if body_lines:
                tail = body_lines[-1].rstrip()
                if tail[-1] not in "。！？：；）」…|" and img_lines < 2:
                    found.append(
                        (
                            "expl_truncated",
                            "解析末行无终止标点且无第二张答案图",
                            tail[-40:],
                        )
                    )
            content_str = (q.get("content") or "").rstrip()
            if content_str.endswith("（"):
                found.append(
                    ("content_open_paren", "题干以未闭合（结尾", content_str[-20:])
                )
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
