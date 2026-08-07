#!/usr/bin/env python3
"""408 四科批量质检修复：选项不全/重复、代码括号、OCR 数字、页眉。"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fix_questions import fix_file  # noqa: E402
from config import COURSE_BY_KEY, OUTPUT_DIR  # noqa: E402

FILES = {
    "ds": OUTPUT_DIR / "questions.json",
    "coa": OUTPUT_DIR / "questions_coa.json",
    "net": OUTPUT_DIR / "questions_net.json",
    "os": OUTPUT_DIR / "questions_os.json",
}


def diagnose(q) -> list[str]:
    stem = q.get("content") or ""
    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
    issues = []
    bal = stem.count("{") - stem.count("}")
    if bal != 0:
        issues.append(f"brace={bal}")
    if re.search(r"第\s*\d+\s*章|\d{4}年.{0,12}考研", stem):
        issues.append("header")
    if re.search(r"==l|!=l|<=l|for\s*\(\s*\w+\s*=\s*l\b|\bn-l\b", stem):
        issues.append("digit_l")
    if q.get("type") == "选择题":
        vals = [str(opts.get(k, "")).strip() for k in "ABCD" if k in opts]
        if len(vals) != 4:
            issues.append(f"opts_n={len(vals)}")
        if vals and len(vals) != len(set(vals)):
            issues.append("dup_opts")
        if any(re.search(r"(?<![A-Za-z])[0○〇]\(", v) for v in vals):
            issues.append("zeroO")
        # 空选项
        if any(k in opts and not str(opts[k]).strip() for k in "ABCD"):
            issues.append("empty_opt")
    return issues


def fix_dup_big_o_options(opts: dict) -> dict:
    """常见：B/D 同为 O(n)，把重复的更高阶候选改成 O(n²)。"""
    if not opts or len(opts) < 4:
        return opts
    vals = {k: str(opts.get(k, "")).strip() for k in "ABCD"}
    # 规范化 0( -> O(
    for k in list(vals):
        vals[k] = re.sub(r"(?<![A-Za-z0-9_])[0○〇]\(([^)]+)\)", r"O(\1)", vals[k])
    # 若恰有一对重复且内容像 O(n)
    from collections import Counter

    c = Counter(vals.values())
    dups = [v for v, n in c.items() if n > 1 and re.match(r"O\s*\(\s*n\s*\)", v.replace(" ", ""))]
    if len(dups) == 1:
        target = dups[0]
        # 最后一个重复的键改为 O(n²)
        seen = False
        for k in "ABCD":
            if vals[k] == target:
                if seen:
                    vals[k] = "O(n²)"
                    break
                seen = True
    return vals


def main():
    # 1) 跑主修复流水线
    for key, path in FILES.items():
        if path.exists():
            fix_file(path, COURSE_BY_KEY[key].pdf_images_dir if key in COURSE_BY_KEY else None, course_key=key)

    report = []
    fixed_extra = 0
    for key, path in FILES.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for ch in data.get("chapters", []):
            for q in ch.get("questions", []):
                before = diagnose(q)
                # 选项 OCR
                opts = q.get("options")
                if isinstance(opts, dict) and opts:
                    new_opts = fix_dup_big_o_options(opts)
                    if new_opts != opts:
                        q["options"] = new_opts
                        fixed_extra += 1
                after = diagnose(q)
                if after:
                    report.append(
                        {
                            "course": key,
                            "id": q.get("id"),
                            "chapter": ch.get("name"),
                            "page": q.get("page"),
                            "issues": after,
                            "stem": (q.get("content") or "")[:100],
                            "opts": q.get("options"),
                        }
                    )
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    out = OUTPUT_DIR / "reports" / "quality_residual.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    by = Counter(i for r in report for i in r["issues"])
    print(f"extra_opt_fixes={fixed_extra}")
    print(f"remaining_issue_questions={len(report)}")
    print("by_issue", dict(by.most_common(20)))
    print(f"wrote {out}")
    for r in report[:25]:
        print(f"  {r['course']} {r['id']} {r['issues']} {(r['stem'] or '')[:50].replace(chr(10),' ')}")


if __name__ == "__main__":
    main()
