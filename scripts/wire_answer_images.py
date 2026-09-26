#!/usr/bin/env python3
"""回写答案图片行到 math-bank data-* 与 output/questions*。

只改 explanation 开头的 answer_crops 图片行，不改题干/选项/choice/解析正文。
"""
from __future__ import annotations
import gzip, json, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "math-bank"
ANSWER_CROP_LINE_RE = re.compile(
    r"^(?:答案图片|解析图片|题图|答图)\s*[：:]\s*answer_crops/", re.IGNORECASE
)

OUT_JSON = {
    "ds": ROOT / "output" / "questions.json",
    "coa": ROOT / "output" / "questions_coa.json",
    "net": ROOT / "output" / "questions_net.json",
    "os": ROOT / "output" / "questions_os.json",
}
COURSE_NAME = {
    "ds": "数据结构",
    "coa": "计算机组成原理",
    "net": "计算机网络",
    "os": "操作系统",
}

def wire_explanation(exp: str, rels: list[str]) -> str:
    kept = [ln for ln in str(exp or "").splitlines() if not ANSWER_CROP_LINE_RE.match(ln.strip())]
    body = "\n".join(kept).strip()
    head = "\n".join(f"答案图片：{r}" for r in rels)
    return head + ("\n\n" + body if body else "")

def iter_questions(data: dict):
    for ch in data.get("chapters", []):
        for q in ch.get("questions", []):
            yield ch, q

def write_course(key: str, data: dict) -> None:
    name = COURSE_NAME[key]
    stem = f"data-{key}"
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (BANK / f"{stem}.json").write_text(payload, encoding="utf-8")
    (BANK / f"{stem}.js").write_text(
        "// Auto-generated — do not edit by hand.\n"
        "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
        f'window.__COURSE_CACHE__["{name}"] = ' + payload + ";\n",
        encoding="utf-8",
    )
    gz = BANK / f"{stem}.json.gz"
    if gz.exists():
        with gzip.open(gz, "wt", encoding="utf-8") as f:
            f.write(payload)

def apply_wiring(plan: list[dict]) -> dict:
    """plan: [{course, topic_title, qid, images:[rel...]}]"""
    by_course: dict[str, list[dict]] = {}
    for it in plan:
        by_course.setdefault(it["course"], []).append(it)

    stats = {"wired": 0, "missing": 0, "out_wired": 0}
    for key, items in by_course.items():
        bank = json.loads((BANK / f"data-{key}.json").read_text(encoding="utf-8"))
        out_path = OUT_JSON[key]
        out = json.loads(out_path.read_text(encoding="utf-8"))
        bank_index = {}
        for _ch, q in iter_questions(bank):
            bank_index[(q.get("topic_title") or "", q.get("id") or "")] = q
        out_index = {}
        for _ch, q in iter_questions(out):
            out_index[(q.get("topic_title") or "", q.get("id") or "")] = q

        for it in items:
            k = (it["topic_title"], it["qid"])
            rels = it["images"]
            if not rels:
                continue
            for index, label in ((bank_index, "bank"), (out_index, "out")):
                q = index.get(k)
                if q is None:
                    stats["missing"] += 1
                    continue
                ans = q.get("answer") or {}
                new_exp = wire_explanation(ans.get("explanation") or "", rels)
                ans["explanation"] = new_exp
                q["answer"] = ans
                if label == "bank":
                    stats["wired"] += 1
                else:
                    stats["out_wired"] += 1

        write_course(key, bank)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[write] data-{key}.json/.js/.gz + {out_path.name}")
    return stats

if __name__ == "__main__":
    plan_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".." / ".." / "temp" / "408-wire-plan.json"
    plan_path = plan_path if plan_path.exists() else Path("temp/408-wire-plan.json")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if isinstance(plan, dict):
        plan = plan["items"]
    stats = apply_wiring(plan)
    print("stats", stats)
