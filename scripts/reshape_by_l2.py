#!/usr/bin/env python3
"""Reshape questions.json by L2 chapter + sub-chapter (choice/app).
用法：python scripts/reshape_by_l2.py [data/toc.json] [output/questions.json] [output/questions.json]
默认：data/toc.json -> output/questions.json -> output/questions.json (in-place)
"""
import json, sys
from collections import Counter, defaultdict

from utils import write_json_atomic

sys.stdout.reconfigure(encoding='utf-8')


def uniquify_ids(questions):
    """L3 题组并入同一 L2 后，再次保证题号在最终章节内唯一。

    post_process.py 只能处理原始 L3 题组内的重复号；多个 L3 合并到同一 L2
    时，A01/X01 可能再次冲突，进而让平台按 source_uid 导入时静默少题。
    """
    seen = Counter()
    for q in questions:
        qid = str(q.get('id') or '').strip()
        if not qid:
            continue
        seen[qid] += 1
        if seen[qid] > 1:
            q['id'] = f'{qid}_{seen[qid]}'
    return questions


def main():
    if len(sys.argv) >= 2:
        toc_json = sys.argv[1]
    else:
        toc_json = 'data/toc/toc.json'
    if len(sys.argv) >= 3:
        input_json = sys.argv[2]
    else:
        input_json = 'output/questions.json'
    if len(sys.argv) >= 4:
        output_json = sys.argv[3]
    else:
        output_json = input_json

    with open(toc_json, encoding='utf-8') as f:
        toc = json.load(f)
    current_l1 = None
    l2_to_info = {}
    for entry in toc:
        if entry[0] == 1:
            parts = entry[1].split(None, 1)
            if len(parts) == 2:
                current_l1 = parts[1]
        elif entry[0] == 2:
            parts = entry[1].split(None, 1)
            if len(parts) == 2:
                num = parts[0]
                name = parts[1].strip()
                l2_to_info[num] = (current_l1, name)

    def l2_of_page(page):
        last = None
        for entry in toc:
            if entry[0] == 2 and entry[2] <= page:
                num = entry[1].split(None, 1)[0]
                last = num
        return last

    with open(input_json, encoding='utf-8') as f:
        data = json.load(f)
    grouped = defaultdict(lambda: {'choice': [], 'app': []})
    for ch in data['chapters']:
        if not ch['questions']:
            continue
        q_start = ch['questions'][0]['page']
        l2_num = l2_of_page(q_start)
        if l2_num is None:
            continue
        if l2_num not in l2_to_info:
            continue
        l1_name, l2_name = l2_to_info[l2_num]
        for q in ch['questions']:
            if q['type'] == '选择题':
                grouped[(l1_name, l2_num, l2_name)]['choice'].append(q)
            else:
                grouped[(l1_name, l2_num, l2_name)]['app'].append(q)

    def sort_key(x):
        num = x[1].replace('*', '')
        return [int(p) for p in num.split('.')]

    new_chapters = []
    for key in sorted(grouped.keys(), key=sort_key):
        l1_name, l2_num, l2_name = key
        bucket = grouped[key]
        uniquify_ids(bucket['choice'])
        uniquify_ids(bucket['app'])
        if bucket['choice']:
            new_chapters.append({
                'name': f'{l1_name} · {l2_name} · 选择题',
                'l1_name': l1_name,
                'l2_num': l2_num,
                'l2_name': l2_name,
                'section_type': '选择题',
                'question_count': len(bucket['choice']),
                'questions': bucket['choice'],
            })
        if bucket['app']:
            new_chapters.append({
                'name': f'{l1_name} · {l2_name} · 解答题',
                'l1_name': l1_name,
                'l2_num': l2_num,
                'l2_name': l2_name,
                'section_type': '解答题',
                'question_count': len(bucket['app']),
                'questions': bucket['app'],
            })

    data['chapters'] = new_chapters
    data['total_questions'] = sum(ch['question_count'] for ch in new_chapters)

    write_json_atomic(output_json, data, indent=2, ensure_ascii=False)
    print(f'Reshaped to {len(new_chapters)} sub-chapters, {data["total_questions"]} questions')
    for ch in new_chapters:
        print(f"  {ch['name']}: {ch['question_count']}")


if __name__ == '__main__':
    main()
