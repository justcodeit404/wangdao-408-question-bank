#!/usr/bin/env python3
"""
题库质量审计增强版：输出 JSON 质量报告，便于定位问题题。
"""
import json
import re
from pathlib import Path
from collections import defaultdict

FILES = {
    '数据结构': 'questions.json',
    '组成原理': 'questions_coa.json',
    '计算机网络': 'questions_net.json',
    '操作系统': 'questions_os.json',
}


def audit_file(path):
    d = json.load(open(path, encoding='utf-8'))
    chapters = d.get('chapters', [])
    total = d.get('total_questions', 0)

    issues = defaultdict(list)
    counts = {
        'no_answer': 0,
        'no_options': 0,
        'empty_content': 0,
        'choice_without_choice': 0,
        'app_with_choice': 0,
        'has_subquestion_markers': 0,
        'has_image_markers': 0,
        'no_image_ref': 0,
    }

    for ch in chapters:
        ch_name = ch.get('name') or ch.get('topic_title', '未知章节')
        for q in ch.get('questions', []):
            ans = q.get('answer') or {}
            content = (q.get('content') or '').strip()
            options = q.get('options')
            qtype = q.get('type')
            qid = q.get('id', '?')
            record = {
                'id': qid,
                'type': qtype,
                'content_preview': content[:80],
                'page': q.get('page'),
            }

            if not content:
                counts['empty_content'] += 1
                issues['empty_content'].append({'chapter': ch_name, **record})

            if not ans or not (ans.get('choice') or ans.get('explanation')):
                counts['no_answer'] += 1
                issues['no_answer'].append({'chapter': ch_name, **record})

            if qtype == '选择题' and not options:
                counts['no_options'] += 1
                issues['no_options'].append({'chapter': ch_name, **record})

            if qtype == '选择题' and not ans.get('choice'):
                counts['choice_without_choice'] += 1
                issues['choice_without_choice'].append({'chapter': ch_name, **record})

            if qtype != '选择题' and ans.get('choice'):
                counts['app_with_choice'] += 1
                issues['app_with_choice'].append({'chapter': ch_name, **record})

            # 仅把全角中文括号 （1）（2）... 视为子问题标记，避免 O(1)、P1() 等半角场景误报
            if re.search(r'（[1-9]\d*）', content):
                counts['has_subquestion_markers'] += 1
                issues['has_subquestion_markers'].append({'chapter': ch_name, **record})

            if '图' in content or '如图' in content or '见下图' in content:
                counts['has_image_markers'] += 1
                if not q.get('has_image') or not q.get('image_ref'):
                    counts['no_image_ref'] += 1
                    issues['no_image_ref'].append({'chapter': ch_name, **record})

    return {
        'total': total,
        'chapters': len(chapters),
        'counts': counts,
        'issues': {k: v[:200] for k, v in issues.items()},
        'issue_totals': {k: len(v) for k, v in issues.items()},
    }


def main():
    report = {'courses': {}, 'summary': {}}
    for course, fn in FILES.items():
        if not Path(fn).exists():
            report['courses'][course] = {'error': f'文件不存在 {fn}'}
            continue
        r = audit_file(fn)
        report['courses'][course] = r

    # 汇总
    total_questions = sum(r['total'] for r in report['courses'].values() if 'total' in r)
    total_issues = {k: 0 for k in report['courses']['数据结构']['counts']}
    for r in report['courses'].values():
        if 'counts' not in r:
            continue
        for k in total_issues:
            total_issues[k] += r['counts'].get(k, 0)

    report['summary'] = {
        'total_questions': total_questions,
        'total_issues': total_issues,
    }

    out_path = Path('quality_report.json')
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'质量报告已保存: {out_path}')
    print(f'总题数: {total_questions}')
    for k, v in total_issues.items():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
