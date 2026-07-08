#!/usr/bin/env python3
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import parse_questions
from parse_patterns import ANSWER_SHORT_RE, ANS_HEADER_RE, answer_header_re, chapter_header_re

data = json.load(open('data/ocr/ds/page_009.json', encoding='utf-8'))
items = parse_questions.get_block_text(data)
lines = parse_questions.group_to_lines(items)

_ans_header_re = answer_header_re()
ans_start_idx = 0
for i, ln in enumerate(lines):
    joined = ' '.join(ln['texts']).strip()
    if _ans_header_re.match(joined):
        ans_start_idx = i
        break

first_text = ' '.join(lines[ans_start_idx]['texts']).strip()
print('Answer header at idx', ans_start_idx, ':', first_text)
answer_lines = lines[ans_start_idx:]

_chapter_header_re = chapter_header_re()
section = 'choice'
for i, ln in enumerate(answer_lines):
    joined = ' '.join(ln['texts']).strip()
    if not joined:
        continue
    cr = _chapter_header_re.match(joined)
    srt = bool(ANSWER_SHORT_RE.match(joined))
    ah = bool(ANS_HEADER_RE.match(joined))
    short50 = joined[:50]
    print('[%d] y=%d chapter=%s short=%s ans_h=%s | %s' % (i, int(ln['y']), bool(cr), srt, ah, short50))
    if cr:
        section = 'app' if ('综合' in cr.group(1) or '解答' in cr.group(1)) else 'choice'
