#!/usr/bin/env python3
"""题库质量审计增强版：输出 JSON 质量报告，便于定位问题题。"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

from config import COURSES

sys.stdout.reconfigure(encoding='utf-8')

# 与 fix_questions.py 保持一致的附图检测规则
IMAGE_MARKERS = [
    '如图', '见下图', '如下图所示', '如图所示', '图中所示',
    '右图', '左图', '下图', '上图', '给出下图', '给出上图',
]
IMAGE_FALSE_POSITIVES = [
    '图的基本概念', '图论', '并查集涉及图', '涉及图', '图的相关', '图的存储',
    '图的遍历', '图的拓扑', '图的最短', '图的最小生成', '图的应用',
    '有向图', '无向图', '连通图', '强连通图', '生成树', '森林',
]


def has_real_image_ref(content):
    if not content:
        return False
    for fp in IMAGE_FALSE_POSITIVES:
        if fp in content:
            return False
    return any(m in content for m in IMAGE_MARKERS)


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

            # 仅把全角中文括号 （1）（2）... 视为子问题标记，避免 O(1)、P1() 等半角场景误报，
            # 也避免函数调用如 func（5）中的括号被误报。
            if re.search(r'(?<![A-Za-z0-9_])（[1-9]\d*）(?![A-Za-z0-9_])', content):
                counts['has_subquestion_markers'] += 1
                issues['has_subquestion_markers'].append({'chapter': ch_name, **record})

            if has_real_image_ref(content):
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
    for c in COURSES:
        if not Path(c.out_json).exists():
            report['courses'][c.name] = {'error': f'文件不存在 {c.out_json}'}
            continue
        r = audit_file(c.out_json)
        report['courses'][c.name] = r

    # 汇总
    total_questions = sum(r['total'] for r in report['courses'].values() if 'total' in r)
    sample_counts = next((r['counts'] for r in report['courses'].values() if 'counts' in r), {})
    total_issues = {k: 0 for k in sample_counts}
    for r in report['courses'].values():
        if 'counts' not in r:
            continue
        for k in total_issues:
            total_issues[k] += r['counts'].get(k, 0)

    report['summary'] = {
        'total_questions': total_questions,
        'total_issues': total_issues,
    }

    out_path = Path('output/reports/quality_report.json')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'质量报告已保存: {out_path}')
    print(f'总题数: {total_questions}')
    for k, v in total_issues.items():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
