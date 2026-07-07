#!/usr/bin/env python3
import sys, re, json
sys.stdout.reconfigure(encoding='utf-8')
import parse_questions

data = json.load(open('ocr/page_009.json', encoding='utf-8'))
items = parse_questions.get_block_text(data)
lines = parse_questions.group_to_lines(items)

ANSWER_HEADER_RE = re.compile(r'^\s*\d+\.\d+(?:\.\d+)?\s*答案与解析')
ans_start_idx = 0
for i, ln in enumerate(lines):
    joined = ' '.join(ln['texts']).strip()
    if ANSWER_HEADER_RE.match(joined):
        ans_start_idx = i
        break

first_text = ' '.join(lines[ans_start_idx]['texts']).strip()
print('Answer header at idx', ans_start_idx, ':', first_text)
answer_lines = lines[ans_start_idx:]

section = 'choice'
for i, ln in enumerate(answer_lines):
    joined = ' '.join(ln['texts']).strip()
    if not joined:
        continue
    chapter_header_re = re.compile(r'^\s*[一二三四五六七八九十]、\s*(单项选择题|综合应用题|填空题|解答题)')
    cr = chapter_header_re.match(joined)
    srt = bool(parse_questions.ANSWER_SHORT_RE.match(joined))
    ah = bool(parse_questions.ANS_HEADER_RE.match(joined))
    short50 = joined[:50]
    print('[%d] y=%d chapter=%s short=%s ans_h=%s | %s' % (i, int(ln['y']), bool(cr), srt, ah, short50))
    if cr:
        section = 'app' if ('综合' in cr.group(1) or '解答' in cr.group(1)) else 'choice'
