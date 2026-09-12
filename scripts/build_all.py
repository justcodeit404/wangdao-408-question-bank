#!/usr/bin/env python3
"""一键构建完整 408 题库。

用法（在项目根目录执行）：
  python scripts/build_all.py

流程（每门课）：
  parse_questions -> post_process -> reshape_by_l2 -> fix_questions
最后：
  merge_courses -> cross_validate_answers -> enhance_audit
"""
import json
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from config import COURSES, OUTPUT_DIR, MATH_BANK_DIR


def run(cmd):
    print(f"\n>> {' '.join(str(x) for x in cmd)}")
    result = subprocess.run(cmd, check=True)
    return result


def main():
    parser = argparse.ArgumentParser(description='构建 408 题库并执行质量门禁')
    parser.add_argument(
        '--skip-vision-audit', action='store_true',
        help='仅供本地开发预览：标记为 unverified，发布打包和 enhance_audit 会拒绝',
    )
    parser.add_argument(
        '--skip-blind-audit', action='store_true',
        help='仅供无模型环境预览；正式发布必须完成独立答案盲解',
    )
    args = parser.parse_args()
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

    # 5. 原书视觉抽检门禁；必须在 merge 前应用持久化补丁，避免 OCR 重建覆盖修复。
    if args.skip_vision_audit:
        MATH_BANK_DIR.mkdir(parents=True, exist_ok=True)
        (MATH_BANK_DIR / 'quality-verification.json').write_text(
            json.dumps({'schema_version': 1, 'status': 'unverified', 'reason': 'explicit_skip'}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        print('[vision-gate] 已显式跳过，产物标记为 unverified（不可发布）')
    else:
        run([sys.executable, 'scripts/vision_quality_gate.py', '--full'])

    # 6. 合并并生成 math-bank 懒加载数据
    run([sys.executable, 'scripts/merge_courses.py', OUTPUT_DIR / 'questions_all.json'])

    # 6.5 有图题精准重裁 + 题干图区碎片清理（必须在 merge 后跑，否则被天真裁图覆盖）
    run([sys.executable, 'scripts/auto_recrop_figs.py'])

    # 7. 交叉验证后锁定本次发布文件哈希，再跑最终审计。
    run([sys.executable, 'scripts/cross_validate_answers.py'])
    if not args.skip_vision_audit:
        run([sys.executable, 'scripts/vision_quality_gate.py', '--finalize'])
        # 统一从当前发布数据重算 ledger 和兼容清单，避免旧 hold 只增不减。
        run([sys.executable, 'scripts/quality_ledger.py'])
        if not args.skip_blind_audit:
            run([sys.executable, 'scripts/blind_answer_gate.py'])
        else:
            print('[blind-gate] 已显式跳过，ledger 保持 pending（不可宣称答案已验算）')
    run([sys.executable, 'scripts/enhance_audit.py'])

    # 8. 答案区原书截图：裁图 + explanation 前置「答案图片」行（幂等）。
    #    必须放在所有读取 explanation 的校验之后（cross_validate 对解析做全等比对）；
    #    ledger 的逐题哈希对截图行不敏感（quality_ledger.stable_explanation），
    #    最后 --refresh-hashes 同步发布文件哈希，避免平台导入拒绝。
    for c in COURSES:
        run([
            sys.executable, 'scripts/gen_answer_crops.py',
            '--course', c.key, '--write-expl',
        ])
    if not args.skip_vision_audit:
        run([sys.executable, 'scripts/quality_ledger.py', '--refresh-hashes'])

    print('\n========== 构建完成 ==========')
    all_json = OUTPUT_DIR / 'questions_all.json'
    data = json.loads(all_json.read_text(encoding='utf-8'))
    print(f'总题数: {data["total_questions"]}')
    for c in data['courses']:
        print(f"  {c['name']}: {c['question_count']} 题 / {c['chapter_count']} 节")


if __name__ == '__main__':
    main()
