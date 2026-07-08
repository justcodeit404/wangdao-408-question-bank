#!/usr/bin/env python3
"""一键构建完整 408 题库。

用法（在项目根目录执行）：
  python scripts/build_all.py

流程（每门课）：
  parse_questions -> post_process -> reshape_by_l2 -> fix_questions
最后：
  merge_courses -> enhance_audit
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from config import COURSES, OUTPUT_DIR


def run(cmd):
    print(f"\n>> {' '.join(str(x) for x in cmd)}")
    result = subprocess.run(cmd, check=True)
    return result


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 备份旧数据
    for c in COURSES:
        src = Path(c.out_json)
        if src.exists():
            bak = src.with_suffix(src.suffix + '.backup')
            shutil.copy2(src, bak)
            print(f'已备份 {src} -> {bak}')

    for c in COURSES:
        print(f"\n========== 处理 {c.name} ==========")
        raw = OUTPUT_DIR / f'questions_{c.key}_raw.json'
        post = OUTPUT_DIR / f'questions_{c.key}_post.json'

        # 1. 解析 OCR -> 结构化题目
        run([
            sys.executable, 'scripts/parse_questions.py',
            '--ocr-dir', c.ocr_dir,
            '--qa-json', c.qa_json,
            '--toc-json', c.toc_json,
            '--output', raw,
            '--title', f'27王道《{c.name}》高清带书签题库',
            '--total-pages', str(c.total_pages),
        ])

        # 2. 拆分选择/解答、加 X/A 前缀、去重
        run([
            sys.executable, 'scripts/post_process.py',
            raw, post,
        ])

        # 3. 按 L2 小节重组
        run([
            sys.executable, 'scripts/reshape_by_l2.py',
            c.toc_json, post, c.out_json,
        ])

        # 4. 自动修复数据质量（提取答案 choice、拆分子问、关联图片）
        run([
            sys.executable, 'scripts/fix_questions.py',
            c.out_json,
        ])

        # 清理中间文件
        Path(raw).unlink(missing_ok=True)
        Path(post).unlink(missing_ok=True)

    # 5. 合并并生成 math-bank 懒加载数据
    run([sys.executable, 'scripts/merge_courses.py', OUTPUT_DIR / 'questions_all.json'])

    # 6. 生成质量报告
    run([sys.executable, 'scripts/enhance_audit.py'])

    print('\n========== 构建完成 ==========')
    all_json = OUTPUT_DIR / 'questions_all.json'
    data = json.loads(all_json.read_text(encoding='utf-8'))
    print(f'总题数: {data["total_questions"]}')
    for c in data['courses']:
        print(f"  {c['name']}: {c['question_count']} 题 / {c['chapter_count']} 节")


if __name__ == '__main__':
    main()
