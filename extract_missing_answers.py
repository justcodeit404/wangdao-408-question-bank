#!/usr/bin/env python3
"""
尝试从答案页 OCR 中补全缺失的答案。
针对 parse_questions.py 漏匹配的情况，用更宽松的模式再扫一轮。
"""
import json
import re
from pathlib import Path
from collections import defaultdict

COURSES = [
    ('数据结构', 'questions.json', 'ocr'),
    ('计算机组成原理', 'questions_coa.json', 'ocr_coa'),
    ('计算机网络', 'questions_net.json', 'ocr_net'),
    ('操作系统', 'questions_os.json', 'ocr_os'),
]


def load_ocr_text(ocr_dir, page):
    path = Path(ocr_dir) / f'page_{page:03d}.json'
    if not path.exists():
        return []
    data = json.load(open(path, encoding='utf-8'))
    blocks = data.get('blocks', [])
    blocks.sort(key=lambda b: (b.get('y0', 0), b.get('x0', 0)))
    return [b.get('text', '') for b in blocks]


def group_to_lines(texts, y_positions=None):
    """简单按行合并（OCR 已经大致有序）"""
    return texts


def extract_choice_answers(texts):
    """从文本中提取短答案 01. C / 1. C 等"""
    result = {}
    for t in texts:
        # 匹配 "01. C"、"1. C"、"01．C"、"01.C" 等
        m = re.match(r'^\s*0?(\d{1,2})[\.．、]\s*([A-Da-d])\s*$', t)
        if m:
            qid = m.group(1).zfill(2)
            result[qid] = m.group(2).upper()
    return result


def extract_app_answers(texts):
    """从文本中提取解答题答案：01.【解答】... 直到下一个题号"""
    result = {}
    i = 0
    while i < len(texts):
        t = texts[i]
        m = re.match(r'^\s*0?(\d{1,2})[\.．、]?\s*[\【\[]?解答[\】\]]?\s*$', t)
        if m:
            qid = m.group(1).zfill(2)
            i += 1
            expl = []
            while i < len(texts):
                t2 = texts[i]
                if re.match(r'^\s*0?\d{1,2}[\.．、]?\s*[\【\[]?解答[\】\]]?\s*$', t2):
                    break
                if re.match(r'^\s*0?\d{1,2}[\.．、]\s*[A-Da-d]\s*$', t2):
                    break
                expl.append(t2)
                i += 1
            result[qid] = '\n'.join(expl).strip()
            continue
        i += 1
    return result


def try_fix_question(q, ocr_dir):
    """尝试从 a_pages 中补全 q 的答案"""
    a_pages = q.get('a_pages', [])
    qtype = q.get('type', '')
    qid = q.get('id', '').lstrip('XA')  # 去掉 X/A 前缀匹配原始题号
    if not qid or not a_pages:
        return None

    all_texts = []
    for p in a_pages:
        all_texts.extend(load_ocr_text(ocr_dir, p))

    if qtype == '选择题':
        choices = extract_choice_answers(all_texts)
        if qid in choices:
            return {'choice': choices[qid], 'explanation': ''}
    else:
        apps = extract_app_answers(all_texts)
        if qid in apps:
            return {'choice': None, 'explanation': apps[qid]}
    return None


def main():
    total_fixed = 0
    for course_name, fn, ocr_dir in COURSES:
        if not Path(fn).exists():
            continue
        data = json.load(open(fn, encoding='utf-8'))
        fixed = 0
        for ch in data.get('chapters', []):
            for q in ch.get('questions', []):
                ans = q.get('answer') or {}
                needs_choice = q.get('type') == '选择题' and not ans.get('choice')
                needs_answer = not ans or not (ans.get('choice') or ans.get('explanation'))
                if not needs_choice and not needs_answer:
                    continue
                new_ans = try_fix_question(q, ocr_dir)
                if new_ans:
                    if not new_ans.get('choice') and not new_ans.get('explanation'):
                        continue
                    q['answer'] = new_ans
                    fixed += 1
        if fixed > 0:
            Path(fn).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'{course_name}: 补全 {fixed} 道题')
            total_fixed += fixed
        else:
            print(f'{course_name}: 未补全')
    print(f'总计补全: {total_fixed}')


if __name__ == '__main__':
    main()
