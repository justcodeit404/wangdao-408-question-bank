#!/usr/bin/env python3
"""单科重抽：渲染切页 → OCR → parse → post → reshape → fix → merge → audit。

用法（在 apps/bank-408 目录）：
  python scripts/rebuild_course.py net
  python scripts/rebuild_course.py net --skip-render --skip-ocr   # 仅重解析
  python scripts/rebuild_course.py net --zoom 2.5
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from config import COURSE_BY_KEY, COURSES, OUTPUT_DIR, PROJECT_ROOT

sys.stdout.reconfigure(encoding="utf-8")


def run(cmd, cwd=None):
    print(f"\n>> {' '.join(str(x) for x in cmd)}")
    subprocess.run(cmd, check=True, cwd=cwd or PROJECT_ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("course", choices=[c.key for c in COURSES])
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--skip-ocr", action="store_true")
    ap.add_argument("--skip-merge", action="store_true", help="不合并四科 / 不写 math-bank")
    ap.add_argument("--zoom", type=float, default=2.0, help="切页渲染倍率")
    ap.add_argument("--force-render", action="store_true")
    ap.add_argument("--force-ocr", action="store_true", help="删除已有 OCR json 后重跑")
    args = ap.parse_args()

    c = COURSE_BY_KEY[args.course]
    print(f"========== 重抽 {c.name} ({c.key}) ==========")
    print(f"PDF: {c.pdf}")
    print(f"OCR: {c.ocr_dir}")
    print(f"IMG: {c.pdf_images_dir}")
    print(f"OUT: {c.out_json}")

    if not c.pdf.exists():
        print(f"[!] PDF 不存在: {c.pdf}")
        sys.exit(1)
    if not c.qa_json.exists():
        print(f"[!] QA 不存在: {c.qa_json}")
        sys.exit(1)
    if not c.toc_json.exists():
        print(f"[!] TOC 不存在: {c.toc_json}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if c.out_json.exists():
        bak = c.out_json.with_suffix(c.out_json.suffix + ".pre_rebuild.bak")
        shutil.copy2(c.out_json, bak)
        print(f"已备份 -> {bak}")

    # 1. 切页
    if not args.skip_render:
        cmd = [
            sys.executable,
            "scripts/render_pdf_pages.py",
            "--course",
            c.key,
            "--zoom",
            str(args.zoom),
        ]
        if args.force_render:
            cmd.append("--force")
        run(cmd)
    else:
        n = len(list(c.pdf_images_dir.glob("page_*.png"))) if c.pdf_images_dir.exists() else 0
        print(f"[skip-render] 现有切页 {n} 张")

    # 2. OCR
    if not args.skip_ocr:
        c.ocr_dir.mkdir(parents=True, exist_ok=True)
        if args.force_ocr:
            for p in c.ocr_dir.glob("page_*.json"):
                p.unlink()
            print("已清空旧 OCR json")
        run(
            [
                sys.executable,
                "scripts/run_ocr.py",
                str(c.qa_json),
                str(c.ocr_dir),
                str(c.pdf_images_dir),
                c.key,
            ]
        )
    else:
        n = len(list(c.ocr_dir.glob("page_*.json"))) if c.ocr_dir.exists() else 0
        print(f"[skip-ocr] 现有 OCR {n} 页")

    ocr_n = len(list(c.ocr_dir.glob("page_*.json"))) if c.ocr_dir.exists() else 0
    if ocr_n == 0:
        print("[!] 无 OCR 结果，中止解析")
        sys.exit(1)

    # 3. 解析流水线
    raw = OUTPUT_DIR / f"questions_{c.key}_raw.json"
    post = OUTPUT_DIR / f"questions_{c.key}_post.json"

    run(
        [
            sys.executable,
            "scripts/parse_questions.py",
            "--ocr-dir",
            c.ocr_dir,
            "--qa-json",
            c.qa_json,
            "--toc-json",
            c.toc_json,
            "--output",
            raw,
            "--title",
            f"27王道《{c.name}》高清带书签题库",
            "--total-pages",
            str(c.total_pages),
        ]
    )
    run([sys.executable, "scripts/post_process.py", raw, post])
    run([sys.executable, "scripts/reshape_by_l2.py", c.toc_json, post, c.out_json])
    run([sys.executable, "scripts/fix_questions.py", c.out_json])

    raw.unlink(missing_ok=True)
    post.unlink(missing_ok=True)

    # 4. 原书视觉门禁 + 合并 + 审计
    if not args.skip_merge:
        run([sys.executable, "scripts/vision_quality_gate.py"])
        run([sys.executable, "scripts/merge_courses.py", OUTPUT_DIR / "questions_all.json"])
        # 有图题精准重裁 + 题干图区碎片清理。merge 会从 output json 重新生成
        # 四科 math-bank 数据（冲掉此前的重裁结果），所以必须全量跑而不是只跑本科。
        run([sys.executable, "scripts/auto_recrop_figs.py"])
        run([sys.executable, "scripts/cross_validate_answers.py"])
        run([sys.executable, "scripts/vision_quality_gate.py", "--finalize"])
        run([sys.executable, "scripts/enhance_audit.py"])

    data = json.loads(c.out_json.read_text(encoding="utf-8"))
    total_q = data.get("total_questions")
    if total_q is None:
        total_q = sum(len(ch.get("questions") or []) for ch in data.get("chapters") or [])
    print(f"\n========== {c.name} 重抽完成: {total_q} 题 ==========")
    print(f"输出: {c.out_json}")


if __name__ == "__main__":
    main()
