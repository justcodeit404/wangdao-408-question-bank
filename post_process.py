#!/usr/bin/env python3
"""
Final post-processing on questions.json:
  1. 把每个 chapter 拆分为 '选择题' + '解答题' 子章
  2. id 加前缀 X/A
  3. 处理重复 id（添加 _2 后缀）
  4. 修复 type 字段为合法值
"""
import json, sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

INPUT_JSON = sys.argv[1] if len(sys.argv) > 1 else 'questions.json'
OUTPUT_JSON = sys.argv[2] if len(sys.argv) > 2 else INPUT_JSON

data = json.load(open(INPUT_JSON, encoding='utf-8'))

new_chapters = []
for ch in data['chapters']:
    choice_qs = [q for q in ch['questions'] if q['type'] == '选择题']
    app_qs = [q for q in ch['questions'] if q['type'] != '选择题']

    if choice_qs:
        nc = dict(ch)
        nc['name'] = ch['topic_title'] + ' · 选择题'
        nc['questions'] = choice_qs
        for q in nc['questions']:
            q['id'] = 'X' + q['id']
        new_chapters.append(nc)
    if app_qs:
        nc = dict(ch)
        nc['name'] = ch['topic_title'] + ' · 解答题'
        nc['questions'] = app_qs
        for q in nc['questions']:
            q['type'] = '计算题'  # 修复type
            q['id'] = 'A' + q['id']
        new_chapters.append(nc)

# Uniquify ids per chapter
for ch in new_chapters:
    seen = Counter()
    for q in ch['questions']:
        qid = q['id']
        if seen[qid] > 0:
            q['id'] = f'{qid}_{seen[qid]+1}'
        seen[qid] += 1

# Recompute question_count
for ch in new_chapters:
    ch['question_count'] = len(ch['questions'])

data['chapters'] = new_chapters
data['total_questions'] = sum(ch['question_count'] for ch in new_chapters)

with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f'Post-processed {INPUT_JSON} -> {OUTPUT_JSON}: {len(new_chapters)} sub-chapters, {data["total_questions"]} questions')
