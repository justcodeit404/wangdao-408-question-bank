"""将已修正的纯正文题干同步到四科发布包。

视觉/质量门禁修正保存在 output/questions*.json，而静态 viewer 的 data-*.json
可能由后续局部脚本生成，二者偶尔发生漂移。本脚本只同步“发布文本有纸面换行、
源文本已连续、且不含代码/分项/表格/图示结构”的题干，避免覆盖需要保留布局的题目。
默认只审计；传入 --apply 才写入 data-*.json、.gz 和 file:// 兼容的 data-*.js。
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
COURSES = {
    "ds": (ROOT / "output/questions.json", ROOT / "math-bank/data-ds.json", "数据结构"),
    "coa": (ROOT / "output/questions_coa.json", ROOT / "math-bank/data-coa.json", "计算机组成原理"),
    "net": (ROOT / "output/questions_net.json", ROOT / "math-bank/data-net.json", "计算机网络"),
    "os": (ROOT / "output/questions_os.json", ROOT / "math-bank/data-os.json", "操作系统"),
}

CODE_RE = re.compile(
    r"\b(?:void|int|char|float|double|for|while|if|else|return|printf|scanf|typedef|struct)\b"
    r"|[{};]|\+\+|--"
)
STRUCTURE_RE = re.compile(
    r"(?:^|\n)\s*(?:[①-⑳]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.．、]?|I{1,4}[.．、]|"
    r"V?I{0,3}[.．、]|[（(]?\d+[)）.．、]|[A-D][.．、]|题目图片：|答案图片：|解析图片：)"
)
TABLE_OR_FIGURE_RE = re.compile(r"(?:如下表|下表|表所示|如下图|下图|图所示)")


def question_map(data: dict) -> dict[tuple[str, str], dict]:
    return {
        (str(ch.get("name") or ""), str(q.get("id") or "")): q
        for ch in data.get("chapters", [])
        for q in ch.get("questions", [])
    }


def is_structured(text: str) -> bool:
    return bool(CODE_RE.search(text) or STRUCTURE_RE.search(text) or TABLE_OR_FIGURE_RE.search(text))


def candidate(source: dict, published: dict) -> bool:
    source_text = str(source.get("content") or "")
    published_text = str(published.get("content") or "")
    return bool(
        "\n" in published_text
        and "\n" not in source_text
        and source_text != published_text
        and not is_structured(published_text)
    )


def compact_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def write_published(path: Path, data: dict, course_name: str) -> None:
    payload = compact_json(data)
    path.write_text(payload, encoding="utf-8")
    gz_path = Path(f"{path}.gz")
    gz_path.write_bytes(gzip.compress(payload.encode("utf-8"), compresslevel=9))
    js_path = path.with_suffix(".js")
    js_path.write_text(
        "// Auto-generated from data JSON; do not edit by hand.\n"
        "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
        f'window.__COURSE_CACHE__[{json.dumps(course_name, ensure_ascii=False)}] = {payload};\n',
        encoding="utf-8",
    )


def reconcile(course_key: str, apply: bool) -> int:
    source_path, published_path, course_name = COURSES[course_key]
    source = json.loads(source_path.read_text(encoding="utf-8"))
    published = json.loads(published_path.read_text(encoding="utf-8"))
    source_rows = question_map(source)
    changed = 0
    for chapter in published.get("chapters", []):
        chapter_name = str(chapter.get("name") or "")
        for question in chapter.get("questions", []):
            source_question = source_rows.get((chapter_name, str(question.get("id") or "")))
            if source_question and candidate(source_question, question):
                question["content"] = source_question["content"]
                changed += 1
    if apply and changed:
        write_published(published_path, published, course_name)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写入发布数据；默认只审计")
    args = parser.parse_args()
    total = 0
    for key in COURSES:
        count = reconcile(key, args.apply)
        total += count
        print(f"[{key}] {'同步' if args.apply else '候选'}纯正文 {count} 题")
    print(f"总计: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
