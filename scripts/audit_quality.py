#!/usr/bin/env python3
"""
题库质量审计：检查 questions_*.json 和 questions_all.json 中的常见问题。
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

FILES = {
    '数据结构': 'output/questions.json',
    '组成原理': 'output/questions_coa.json',
    '计算机网络': 'output/questions_net.json',
    '操作系统': 'output/questions_os.json',
}


def audit_file(path):
    d = json.load(open(path, encoding='utf-8'))
    chapters = d.get('chapters', [])
    total = d.get('total_questions', 0)

    no_answer = 0
    no_options = 0
    empty_content = 0
    choice_without_choice = 0  # type=选择题 但 answer.choice 为空
    app_with_choice = 0  # type=综合应用题 但 answer.choice 有值
    has_subquestion_markers = 0
    has_image_markers = 0
    flagged = []

    for ch in chapters:
        for q in ch.get('questions', []):
            ans = q.get('answer') or {}
            content = (q.get('content') or '').strip()
            options = q.get('options')
            qtype = q.get('type')

            if not content:
                empty_content += 1
            if not ans or not (ans.get('choice') or ans.get('explanation')):
                no_answer += 1
                flagged.append((ch.get('name'), q.get('id'), 'no_answer', content[:40]))
            if qtype == '选择题' and not options:
                no_options += 1
                flagged.append((ch.get('name'), q.get('id'), 'no_options', content[:40]))
            if qtype == '选择题' and not ans.get('choice'):
                choice_without_choice += 1
            if qtype != '选择题' and ans.get('choice'):
                app_with_choice += 1
            if '（1）' in content or '（2）' in content or '(1)' in content or '(2)' in content:
                has_subquestion_markers += 1
            if '图' in content or '如图' in content or '见下图' in content:
                has_image_markers += 1

    return {
        'total': total,
        'chapters': len(chapters),
        'no_answer': no_answer,
        'no_options': no_options,
        'empty_content': empty_content,
        'choice_without_choice': choice_without_choice,
        'app_with_choice': app_with_choice,
        'has_subquestion_markers': has_subquestion_markers,
        'has_image_markers': has_image_markers,
        'flagged': flagged[:20],
    }


def main():
    for course, fn in FILES.items():
        if not Path(fn).exists():
            print(f"{course}: 文件不存在 {fn}")
            continue
        r = audit_file(fn)
        print(f"\n=== {course} ({fn}) ===")
        print(f"总题数: {r['total']}, 章数: {r['chapters']}")
        print(f"无答案: {r['no_answer']}")
        print(f"选择题无选项: {r['no_options']}")
        print(f"空题干: {r['empty_content']}")
        print(f"选择题缺 choice: {r['choice_without_choice']}")
        print(f"应用题带 choice: {r['app_with_choice']}")
        print(f"含子问标记（未拆分）: {r['has_subquestion_markers']}")
        print(f"题干含“图”字（可能丢图）: {r['has_image_markers']}")
        if r['flagged']:
            print("前 20 条异常样例:")
            for name, qid, reason, text in r['flagged']:
                print(f"  [{reason}] {name} #{qid}: {text}")


if __name__ == '__main__':
    main()
