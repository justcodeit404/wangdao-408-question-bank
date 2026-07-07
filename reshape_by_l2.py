#!/usr/bin/env python3
"""Reshape questions.json by L2 chapter + sub-chapter (choice/app).
用法：python reshape_by_l2.py [toc.json] [questions.json] [output.json]
默认：toc.json -> questions.json -> questions.json (in-place)
"""
import json, sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding='utf-8')

if len(sys.argv) >= 2:
    TOC_JSON = sys.argv[1]
else:
    TOC_JSON = 'toc.json'
if len(sys.argv) >= 3:
    INPUT_JSON = sys.argv[2]
else:
    INPUT_JSON = 'questions.json'
if len(sys.argv) >= 4:
    OUTPUT_JSON = sys.argv[3]
else:
    OUTPUT_JSON = INPUT_JSON

TOC = json.load(open(TOC_JSON, encoding='utf-8'))
current_l1 = None
l2_to_info = {}
for entry in TOC:
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
    for entry in TOC:
        if entry[0] == 2 and entry[2] <= page:
            num = entry[1].split(None, 1)[0]
            last = num
    return last

data = json.load(open(INPUT_JSON, encoding='utf-8'))
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
    if bucket['choice']:
        nc = {
            'name': f'{l1_name} · {l2_name} · 选择题',
            'l1_name': l1_name,
            'l2_num': l2_num,
            'l2_name': l2_name,
            'section_type': '选择题',
            'question_count': len(bucket['choice']),
            'questions': bucket['choice'],
        }
        new_chapters.append(nc)
    if bucket['app']:
        nc = {
            'name': f'{l1_name} · {l2_name} · 解答题',
            'l1_name': l1_name,
            'l2_num': l2_num,
            'l2_name': l2_name,
            'section_type': '解答题',
            'question_count': len(bucket['app']),
            'questions': bucket['app'],
        }
        new_chapters.append(nc)

data['chapters'] = new_chapters
data['total_questions'] = sum(ch['question_count'] for ch in new_chapters)

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f'Reshaped to {len(new_chapters)} sub-chapters, {data["total_questions"]} questions')
for ch in new_chapters:
    print(f"  {ch['name']}: {ch['question_count']}")
