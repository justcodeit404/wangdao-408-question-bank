#!/usr/bin/env python3
"""
一键构建完整 408 题库：
parse_questions -> post_process -> reshape_by_l2 -> merge -> build_data_js -> build_html
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

COURSES = [
    {
        'key': 'ds',
        'name': '数据结构',
        'pdf': '27王道《数据结构》高清带书签.pdf',
        'ocr_dir': 'ocr',
        'qa_json': 'scripts_output/qa_pairs.json',
        'toc_json': 'toc.json',
        'total_pages': 397,
        'out_json': 'questions.json',
        'pdf_images_dir': 'pdf_images',
    },
    {
        'key': 'coa',
        'name': '计算机组成原理',
        'pdf': '27王道《计算机组成原理》高清带书签.pdf',
        'ocr_dir': 'ocr_coa',
        'qa_json': 'scripts_output/coa_qa_pairs.json',
        'toc_json': 'toc_coa.json',
        'total_pages': 333,
        'out_json': 'questions_coa.json',
        'pdf_images_dir': 'pdf_images_coa',
    },
    {
        'key': 'net',
        'name': '计算机网络',
        'pdf': '27王道《计算机网络》高清带书签.pdf',
        'ocr_dir': 'ocr_net',
        'qa_json': 'scripts_output/net_qa_pairs.json',
        'toc_json': 'toc_net.json',
        'total_pages': 309,
        'out_json': 'questions_net.json',
        'pdf_images_dir': 'pdf_images_net',
    },
    {
        'key': 'os',
        'name': '操作系统',
        'pdf': '27王道《操作系统》高清带书签.pdf',
        'ocr_dir': 'ocr_os',
        'qa_json': 'scripts_output/os_qa_pairs.json',
        'toc_json': 'toc_os.json',
        'total_pages': 365,
        'out_json': 'questions_os.json',
        'pdf_images_dir': 'pdf_images_os',
    },
]


def run(cmd):
    print(f"\n>> {' '.join(cmd)}")
    result = subprocess.run(cmd, check=True)
    return result


def main():
    # 备份旧数据
    for c in COURSES:
        src = Path(c['out_json'])
        if src.exists():
            bak = src.with_suffix(src.suffix + '.backup')
            shutil.copy2(src, bak)
            print(f"已备份 {src} -> {bak}")

    for c in COURSES:
        print(f"\n========== 处理 {c['name']} ==========")
        raw = f"questions_{c['key']}_raw.json"

        # 1. parse_questions
        run([
            sys.executable, 'parse_questions.py',
            '--ocr-dir', c['ocr_dir'],
            '--qa-json', c['qa_json'],
            '--toc-json', c['toc_json'],
            '--output', raw,
            '--title', f"27王道《{c['name']}》高清带书签题库",
            '--total-pages', str(c['total_pages']),
        ])

        # 2. post_process (添加 X/A 前缀、拆分选择/解答)
        post = f"questions_{c['key']}_post.json"
        run([
            sys.executable, 'post_process.py',
            raw, post,
        ])

        # 3. reshape_by_l2 (按 L2 小节重组)
        run([
            sys.executable, 'reshape_by_l2.py',
            c['toc_json'], post, c['out_json'],
        ])

        # 4. 自动修复数据质量（提取答案 choice、拆分子问、关联图片）
        run([
            sys.executable, 'fix_questions.py',
            c['out_json'],
        ])

        # 清理中间文件
        Path(raw).unlink(missing_ok=True)
        Path(post).unlink(missing_ok=True)

    # 5. 合并并生成 math-bank 懒加载数据（data.js loader + data-<key>.js）
    run([sys.executable, 'merge_courses.py', 'questions_all.json'])

    # 6. 生成质量报告
    run([sys.executable, 'enhance_audit.py'])

    print("\n========== 构建完成 ==========")
    # 打印最终统计
    data = json.loads(Path('questions_all.json').read_text(encoding='utf-8'))
    print(f"总题数: {data['total_questions']}")
    for c in data['courses']:
        print(f"  {c['name']}: {c['question_count']} 题 / {c['chapter_count']} 节")


if __name__ == '__main__':
    main()
