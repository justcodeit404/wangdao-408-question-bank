#!/usr/bin/env python3
"""扫描网络题库残题，输出 JSON + Markdown 清单。"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "output" / "questions_net.json"
OUT_JSON = ROOT / "output" / "reports" / "net_residuals.json"
OUT_MD = ROOT / "output" / "reports" / "net_residuals.md"


def opts_dict(q):
    o = q.get("options") or {}
    if isinstance(o, list):
        return {chr(65 + i): str(v) for i, v in enumerate(o)}
    return {k: str(v) for k, v in o.items()}


def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    issues = []

    for ch in data["chapters"]:
        chn = ch.get("name") or ""
        for q in ch.get("questions", []):
            qid = q.get("id")
            qtype = q.get("type")
            stem = q.get("content") or ""
            ans = q.get("answer") or {}
            choice = (ans.get("choice") or "").strip()
            expl = (ans.get("explanation") or "").strip()
            od = opts_dict(q)
            tags = []

            if qtype == "选择题":
                keys = [k for k in "ABCD" if k in od]
                texts = [od.get(k, "").strip() for k in "ABCD"]
                if len([t for t in texts if t]) != 4 or len(keys) != 4:
                    tags.append("opt_incomplete")
                if any(not od.get(k, "").strip() for k in keys):
                    tags.append("empty_opt")
                vals = [od.get(k, "").strip() for k in keys]
                if vals and len(vals) != len(set(vals)):
                    tags.append("dup_opt")
                if any(re.search(r"\n[①②]?\s*A[\.．、]", od.get(k, "")) for k in keys):
                    tags.append("opt_bleed")
                if any(len(od.get(k, "")) > 180 for k in keys):
                    tags.append("opt_too_long")
                if not choice:
                    tags.append("no_choice")
                if not expl:
                    tags.append("no_expl")
                blanks = len(re.findall(r"[（(]\s*[①②③④1-4]?\s*[）)]", stem))
                if blanks >= 2 and len(choice) > 1:
                    tags.append("multi_blank")
            else:
                if not expl:
                    tags.append("no_expl_app")

            if re.search(r"如下图|下图所示|见图|图\s*\d", stem) and not q.get("has_image"):
                tags.append("figure_no_img")
            if stem.rstrip().endswith(("，", "、", "：", ":", "（", "(")):
                tags.append("stem_trunc")
            if re.search(r"[0-9a-f]{8}\s+[0-9a-f]{8}", stem, re.I):
                tags.append("hex_pollution")
            if "□" in stem or re.search(r"[○〇]\(", stem):
                tags.append("ocr_glyph")

            if tags:
                issues.append(
                    {
                        "id": qid,
                        "type": qtype,
                        "chapter": chn,
                        "page": q.get("page"),
                        "tags": tags,
                        "choice": choice,
                        "stem": stem[:160].replace("\n", " "),
                        "opts": {k: od.get(k, "")[:80] for k in "ABCD" if k in od},
                        "has_image": bool(q.get("has_image")),
                        "a_pages": q.get("a_pages"),
                        "q_pages": q.get("q_pages"),
                    }
                )

    sev = {
        "opt_incomplete": 0,
        "empty_opt": 1,
        "opt_bleed": 2,
        "hex_pollution": 3,
        "multi_blank": 4,
        "dup_opt": 5,
        "no_expl": 6,
        "no_expl_app": 7,
        "figure_no_img": 8,
        "stem_trunc": 9,
        "opt_too_long": 10,
        "ocr_glyph": 11,
        "no_choice": 0,
    }
    issues.sort(key=lambda x: min(sev.get(t, 99) for t in x["tags"]))

    by = defaultdict(int)
    for i in issues:
        for t in i["tags"]:
            by[t] += 1

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    report = {"total": len(issues), "by_tag": dict(by), "items": issues}
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 计算机网络 残题清单",
        "",
        f"共 **{len(issues)}** 道待处理（可重叠标签）。",
        "",
        "## 标签统计",
        "",
    ]
    for k, v in sorted(by.items(), key=lambda x: -x[1]):
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## 明细", ""]
    for i, it in enumerate(issues, 1):
        lines.append(
            f"### {i}. {it['id']} · p{it['page']} · {it['type']}\n"
            f"- 章节：{it['chapter']}\n"
            f"- 标签：{', '.join(it['tags'])}\n"
            f"- 答案：`{it['choice'] or '-'}`\n"
            f"- 题干：{it['stem']}\n"
            f"- 选项：`{it['opts']}`\n"
        )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"total={len(issues)}")
    print("by_tag", dict(sorted(by.items(), key=lambda x: -x[1])))
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    # hard bugs first
    hard = [
        i
        for i in issues
        if set(i["tags"])
        & {"opt_incomplete", "empty_opt", "opt_bleed", "hex_pollution", "dup_opt", "no_expl_app", "no_choice"}
    ]
    print(f"hard_bugs={len(hard)}")
    for i in hard:
        print(f"  {i['id']} p{i['page']} {i['tags']} {i['chapter'][:30]}")


if __name__ == "__main__":
    main()
