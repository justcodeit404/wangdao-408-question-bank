#!/usr/bin/env python3
"""中间态 output/questions*.json 与 curated 产物漂移后的反向修复。

背景（ocr-fixes.md 2026-09-29）：math-bank/data-*.json 是 curated 真理源，
output/questions*.json 只是 OCR 解析→fix_questions 的中间态。09-29 事故后 ds
中间态与产物漂移 764/794 题（缺「树与二叉树·树的基本概念·X08」、多出 3 个游离
A01/X03_2），fix_questions 严格校验在缺失补丁目标处中断，rebuild_bank 无法完成；
而全量重跑 OCR 重建会引入新一轮 OCR 误差、且 695 条补丁的题号对不上。

本脚本按产物重建指定课程的中间态（题目/章节键完全一致，仅去掉 merge_courses
会重新注入的 chapter.course），使管线恢复可重建。幂等：产物不变时重复执行无效果。

用法：python scripts/resync_intermediate_from_bank.py [ds|coa|os|net ...]（默认 ds）
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import COURSES, MATH_BANK_DIR  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

KEYS = {c.key: c for c in COURSES}


def resync(key: str) -> None:
    course = KEYS[key]
    bank_path = MATH_BANK_DIR / f"data-{key}.json"
    out_path = course.out_json
    bank = json.loads(bank_path.read_text(encoding="utf-8"))

    out: dict = {"title": bank["title"], "total_pages": course.total_pages,
                 "total_questions": 0, "chapters": []}
    for ch in bank["chapters"]:
        ch = {k: v for k, v in ch.items() if k != "course"}
        out["chapters"].append(ch)
        out["total_questions"] += ch["question_count"]

    if out_path.exists() and not out_path.with_suffix(".presync.bak").exists():
        shutil.copy2(out_path, out_path.with_suffix(".presync.bak"))
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[resync] {out_path.name} <- {bank_path.name}: "
          f"{len(out['chapters'])} 节, {out['total_questions']} 题")


def main() -> None:
    args = sys.argv[1:] or ["ds"]
    for key in args:
        if key not in KEYS:
            sys.exit(f"unknown course key: {key} (choose from {sorted(KEYS)})")
        resync(key)


if __name__ == "__main__":
    main()
