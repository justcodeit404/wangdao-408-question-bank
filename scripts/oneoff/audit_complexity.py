#!/usr/bin/env python3
"""审查全库「时间复杂度」相关题，输出报告并尝试自动修复。"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fix_questions import (  # noqa: E402
    fix_big_o_option,
    fix_code_in_content,
    fix_common_ocr_errors,
    clean_content,
    clean_option_text,
    clean_option_trailing_punct,
)

OUT_JSON = ROOT / "output" / "reports" / "complexity_audit.json"
OUT_MD = ROOT / "output" / "reports" / "complexity_audit.md"

FILES = {
    "ds": ROOT / "output" / "questions.json",
    "coa": ROOT / "output" / "questions_coa.json",
    "net": ROOT / "output" / "questions_net.json",
    "os": ROOT / "output" / "questions_os.json",
}

KW = re.compile(r"时间复杂度|频度|执行次数|渐近复杂度|算法的时间|程序段的时间|基本运算")
CODE_HINT = re.compile(r"\b(void|int|for|while|if|return|printf|typedef)\b|[;{}]")


def is_complexity_q(stem: str, opts: dict) -> bool:
    blob = stem + " " + " ".join(str(v) for v in opts.values())
    if not KW.search(blob) and not re.search(r"O\s*\([^)]+\)", blob):
        return False
    # 排除纯「空间复杂度」且无时间
    if "空间复杂度" in stem and "时间复杂度" not in stem and "频度" not in stem and "执行次数" not in stem:
        # 仍可能选项里全是 O() 讲时间——若题干明确只问空间则跳过
        if re.search(r"空间复杂度为|空间复杂度是|空间复杂度为O", stem) and "时间" not in stem:
            return False
    # 需要明确与时间/频度/O() 判定相关
    if re.search(r"时间复杂度|频度|执行次数", blob):
        return True
    if re.search(r"下列.*复杂度|程序段|算法.*O\s*\(", stem) and re.search(r"O\s*\(", blob):
        return True
    return False


def diagnose(stem: str, opts: dict, qtype: str, ans: dict) -> list[str]:
    issues = []
    bal = stem.count("{") - stem.count("}")
    if bal != 0:
        issues.append(f"brace_bal={bal}")
    if re.search(
        r"==l|!=l|<=l|>=l|(?<![A-Za-z_])l(?==)|for\s*\(\s*\w+\s*=\s*l\b|\b[ijkmn]\s*=\s*l\b|\bn-l\b|\b\w\+l\b",
        stem,
    ):
        issues.append("digit_l")
    if re.search(r"第\s*\d+\s*章|\d{4}年.{0,12}考研", stem):
        issues.append("header_noise")
    vals = [str(opts.get(k, "")).strip() for k in "ABCD" if k in opts]
    if qtype == "选择题":
        if len(vals) != 4:
            issues.append(f"opts_n={len(vals)}")
        if vals and len(vals) != len(set(vals)):
            issues.append("dup_opts")
        if any(re.search(r"(?<![A-Za-z])[0○〇]\(", v) for v in vals):
            issues.append("zero_O")
        if any(re.fullmatch(r"O\s*\(\s*3\s*/\s*n\s*\)", v.replace(" ", "")) for v in vals):
            issues.append("bad_cube_root")
        if not (ans.get("choice") or "").strip():
            issues.append("no_choice")
    if stem.rstrip().endswith(("，", "、", "：", "(", "（")):
        issues.append("stem_trunc")
    if CODE_HINT.search(stem) and re.search(r"\n\s*else\s*\{", stem) and "}else" not in stem.replace(" ", ""):
        # rough: else after open without close — may already fixed
        pass
    # 代码块明显未闭合（有函数头无结尾）
    if re.search(r"\b(void|int|char)\s+\w+\s*\([^)]*\)\s*\{", stem) and bal > 0:
        issues.append("func_unclosed")
    return issues


def auto_fix_question(q: dict) -> bool:
    """返回是否改动。"""
    changed = False
    stem0 = q.get("content") or ""
    stem = clean_content(stem0)
    stem = fix_common_ocr_errors(stem)
    stem = fix_code_in_content(stem)
    if stem != stem0:
        q["content"] = stem
        changed = True

    opts = q.get("options")
    if isinstance(opts, dict) and opts:
        new_opts = {}
        for k, v in opts.items():
            nv = clean_option_trailing_punct(
                fix_big_o_option(fix_common_ocr_errors(clean_option_text(str(v))))
            )
            new_opts[k] = nv
            if nv != str(v).strip() and nv != v:
                changed = True
        # 去重启发式：若 C/D 都是 O(n) 且答案指向更高阶，不在这里猜
        q["options"] = new_opts

    ans = q.get("answer") or {}
    if ans.get("explanation"):
        e0 = ans["explanation"]
        e1 = fix_code_in_content(fix_common_ocr_errors(clean_content(e0)))
        if e1 != e0:
            ans["explanation"] = e1
            q["answer"] = ans
            changed = True
    return changed


# 数据结构·算法评价 已知正确选项（对照 OCR 答案页 + 旧版）
DS_ALGO_OPTION_PATCHES = {
    # chapter key fragment, id -> options
    ("算法和算法评价", "X06"): {
        "A": "O(n)",
        "B": "O(n²)",
        "C": "O(nlog2n)",
        "D": "O(log2n)",
    },
    ("算法和算法评价", "X07"): {
        "A": "O(n)",
        "B": "O(nlog2n)",
        "C": "O(n^{1/3})",
        "D": "O(√n)",
    },
    ("算法和算法评价", "X08"): {
        "A": "O(n)",
        "B": "O(nlog2n)",
        "C": "O(n³)",
        "D": "O(n²)",
    },
    ("算法和算法评价", "X11"): {
        "A": "O(n)",
        "B": "O(nlog2n)",
        "C": "O(log2n)",
        "D": "O(n²)",
    },
    ("算法和算法评价", "X12"): {
        "A": "O(log2n)",
        "B": "O(n)",
        "C": "O(nlog2n)",
        "D": "O(n²)",
    },
}

# 综合题：多段代码被 OCR 粘连时的标准拆分
DS_CONTENT_PATCHES = {
    ("算法和算法评价", "A01"): (
        "分析下列各程序段，求出算法的时间复杂度。\n"
        "① i=1; k=0;\n"
        "while(i<n-1) {\n"
        "    k=k+10*i;\n"
        "    i++;\n"
        "}\n"
        "② y=0;\n"
        "while((y+1)*(y+1)<=n)\n"
        "    y=y+1;\n"
        "③ for(i=0;i<n;i++)\n"
        "    for(j=0;j<m;j++)\n"
        "        a[i][j]=0;",
        "① 基本语句 k=k+10*i 共执行了 n-2 次，故 T(n)=O(n)。\n"
        "② 设循环体共执行 t 次，每循环一次循环变量 y 加 1，最终 t=y。"
        "由 (y+1)²≤n 得 t≤√n-1，故 T(n)=O(√n)。\n"
        "③ 内循环执行 m 次，外循环执行 n 次，共执行 mn 次，故 T(m,n)=O(mn)。",
    ),
}


def apply_known_patches(course: str, ch_name: str, q: dict) -> bool:
    if course != "ds":
        return False
    qid = q.get("id")
    changed = False
    for (ch_key, pid), opts in DS_ALGO_OPTION_PATCHES.items():
        if pid == qid and ch_key in ch_name:
            if q.get("options") != opts:
                q["options"] = dict(opts)
                changed = True
    for (ch_key, pid), (content, expl) in DS_CONTENT_PATCHES.items():
        if pid == qid and ch_key in ch_name:
            if q.get("content") != content:
                q["content"] = content
                changed = True
            ans = q.get("answer") or {}
            if expl and ans.get("explanation") != expl:
                ans["explanation"] = expl
                ans.setdefault("choice", None)
                q["answer"] = ans
                changed = True
    return changed


def main():
    all_rows = []
    fixed_total = 0

    for course, path in FILES.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        course_fixed = 0
        for ch in data.get("chapters", []):
            ch_name = ch.get("name") or ""
            for q in ch.get("questions", []):
                stem = q.get("content") or ""
                opts = q.get("options") if isinstance(q.get("options"), dict) else {}
                if not is_complexity_q(stem, opts or {}):
                    continue

                if auto_fix_question(q):
                    course_fixed += 1
                if apply_known_patches(course, ch_name, q):
                    course_fixed += 1

                stem = q.get("content") or ""
                opts = q.get("options") if isinstance(q.get("options"), dict) else {}
                ans = q.get("answer") or {}
                issues = diagnose(stem, opts, q.get("type") or "", ans)

                all_rows.append(
                    {
                        "course": course,
                        "id": q.get("id"),
                        "type": q.get("type"),
                        "chapter": ch_name,
                        "page": q.get("page"),
                        "choice": (ans.get("choice") or ""),
                        "issues": issues,
                        "has_code": bool(CODE_HINT.search(stem)),
                        "stem": stem,
                        "options": opts,
                        "expl_preview": ((ans.get("explanation") or "")[:200]),
                    }
                )

        if course_fixed:
            # recount
            for ch in data.get("chapters", []):
                ch["question_count"] = len(ch.get("questions") or [])
            data["total_questions"] = sum(ch["question_count"] for ch in data["chapters"])
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{course}] wrote fixes, ops~={course_fixed}")
            fixed_total += course_fixed
        else:
            print(f"[{course}] no file write needed")

    # report
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    issue_rows = [r for r in all_rows if r["issues"]]
    lines = [
        "# 时间复杂度题审查报告",
        "",
        f"- 共审查：**{len(all_rows)}** 题",
        f"- 含代码：**{sum(1 for r in all_rows if r['has_code'])}** 题",
        f"- 仍有问题：**{len(issue_rows)}** 题",
        f"- 本轮自动修复写入约：**{fixed_total}** 次改动",
        "",
        "## 按科目",
        "",
    ]
    by = Counter(r["course"] for r in all_rows)
    for k, v in by.items():
        bad = sum(1 for r in all_rows if r["course"] == k and r["issues"])
        lines.append(f"- `{k}`: {v} 题（问题 {bad}）")

    lines += ["", "## 问题分布", ""]
    for k, v in Counter(i for r in all_rows for i in r["issues"]).most_common():
        lines.append(f"- `{k}`: {v}")

    lines += ["", "## 明细（全部）", ""]
    for i, r in enumerate(all_rows, 1):
        flag = "⚠️" if r["issues"] else "✅"
        lines.append(
            f"### {i}. {flag} [{r['course']}] {r['id']} · p{r['page']} · {r['type']}\n"
            f"- 章节：{r['chapter']}\n"
            f"- 答案：`{r['choice'] or '-'}`\n"
            f"- 问题：{', '.join(r['issues']) if r['issues'] else '无'}\n"
            f"- 题干：\n\n```\n{r['stem']}\n```\n"
            f"- 选项：`{r['options']}`\n"
        )

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"TOTAL {len(all_rows)} issues_left {len(issue_rows)}")
    print(f"wrote {OUT_MD}")
    for r in issue_rows:
        print(
            f"  ! {r['course']} {r['id']} {r['issues']} "
            f"{r['stem'][:60].replace(chr(10), ' ')}"
        )


if __name__ == "__main__":
    main()
