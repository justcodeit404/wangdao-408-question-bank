#!/usr/bin/env python3
"""
从 TOC JSON 中直接提取「本节试题精选」和「答案与解析」的页边界，生成 qa_pairs.json。

TOC 条目格式：[level, title, page]
  level 3: 1.1.3 本节试题精选 / 1.1.4 答案与解析
  level 4: 一、单项选择题 / 二、综合应用题

用法：
  python scripts/regenerate_qa_pairs.py --toc-json data/toc.json --total-pages 397 --output data/qa_pairs.json
  python scripts/regenerate_qa_pairs.py --toc-json data/toc_coa.json --total-pages 333 --output data/coa_qa_pairs.json
  python scripts/regenerate_qa_pairs.py --toc-json data/toc_net.json --total-pages 309 --output data/net_qa_pairs.json
  python scripts/regenerate_qa_pairs.py --toc-json data/toc_os.json --total-pages 365 --output data/os_qa_pairs.json
"""
import json
import re
import sys
from pathlib import Path

SECTION_RE = re.compile(r'^\s*(\d+\.\d+(?:\.\d+)?)\s*(本节试题精选|本节习题精选)\s*$')
ANSWER_RE = re.compile(r'^\s*(\d+\.\d+(?:\.\d+)?)\s*答案与解析\s*$')
SUBSECTION_RE = re.compile(r'^\s*(?:[一二三四五六七八九十][、．])?\s*(单项选择题|综合应用题|填空题|解答题)\s*$')


def load_toc(path):
    data = json.load(open(path, encoding='utf-8'))
    # 兼容 [{level,title,page}] 或 [[level,title,page]]
    entries = []
    for e in data:
        if isinstance(e, dict):
            entries.append((e.get('level', e.get('Level')), e.get('title', e.get('Title')), e.get('page', e.get('Page'))))
        elif isinstance(e, (list, tuple)) and len(e) >= 3:
            entries.append((e[0], e[1], e[2]))
    return entries


def extract_sections(entries):
    """从 TOC 条目中提取 question/answer/subsection 列表。"""
    q_sections = []
    a_sections = []
    sub_sections = []
    for level, title, page in entries:
        title = (title or '').strip()
        if not title:
            continue
        m = SECTION_RE.match(title)
        if m:
            q_sections.append({'num': m.group(1), 'title': title, 'page': page})
            continue
        m = ANSWER_RE.match(title)
        if m:
            a_sections.append({'num': m.group(1), 'title': title, 'page': page})
            continue
        m = SUBSECTION_RE.match(title)
        if m:
            sub_sections.append({'type': m.group(1), 'title': title, 'page': page})
    return q_sections, a_sections, sub_sections


def find_matching_answer(q, a_sections):
    """为 question section 找到匹配的 answer section。
    匹配规则：在 question 之后，section_num 相同或末尾 +1。
    """
    for a in a_sections:
        if a['page'] < q['page']:
            continue
        if a['num'] == q['num'] or self_plus_one(a['num'], q['num']):
            return a
    return None


def self_plus_one(anum, qnum):
    """判断 anum 是否是 qnum 最后一位 +1，如 1.1.4 vs 1.1.3。"""
    ap = anum.split('.')
    qp = qnum.split('.')
    if len(ap) != len(qp):
        return False
    if ap[:-1] != qp[:-1]:
        return False
    try:
        return int(ap[-1]) == int(qp[-1]) + 1
    except ValueError:
        return False


def find_subsections_between(sub_sections, start_page, end_page):
    """找 [start_page, end_page) 范围内的子题型标题。"""
    result = []
    seen = set()
    for s in sub_sections:
        p = s['page']
        if start_page <= p < end_page:
            key = (p, s['type'])
            if key in seen:
                continue
            seen.add(key)
            result.append([4, s['type'], p])
    return result


def pair_qa(entries, total_pages):
    """把 question section 和 answer section 配对。"""
    q_sections, a_sections, sub_sections = extract_sections(entries)
    pairs = []
    for i, q in enumerate(q_sections):
        next_q_page = q_sections[i + 1]['page'] if i + 1 < len(q_sections) else total_pages + 1
        a = find_matching_answer(q, a_sections)
        if a is None:
            pairs.append({
                'topic_title': clean_title(q['title']),
                'q_start': q['page'],
                'q_children': find_subsections_between(sub_sections, q['page'], next_q_page),
                'ans_entry': None,
                'a_start': next_q_page,
                'a_children': [],
                'q_end': next_q_page,
                'q_pagecount': next_q_page - q['page'],
            })
            continue

        pairs.append({
            'topic_title': clean_title(q['title']),
            'q_start': q['page'],
            'q_children': find_subsections_between(sub_sections, q['page'], a['page']),
            'ans_entry': [3, clean_title(a['title']), a['page']],
            'a_start': a['page'],
            'a_children': find_subsections_between(sub_sections, a['page'], next_q_page),
            'q_end': next_q_page,
            'q_pagecount': next_q_page - q['page'],
        })
    return pairs


def clean_title(text):
    """清理标题，统一空格。"""
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def main():
    toc_json = 'data/toc/toc.json'
    total_pages = 397
    output = 'data/qa/qa_pairs.json'

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--toc-json' and i + 1 < len(args):
            toc_json = args[i + 1]; i += 2
        elif a == '--total-pages' and i + 1 < len(args):
            total_pages = int(args[i + 1]); i += 2
        elif a == '--output' and i + 1 < len(args):
            output = args[i + 1]; i += 2
        else:
            i += 1

    print(f'Loading TOC {toc_json}...')
    entries = load_toc(toc_json)
    pairs = pair_qa(entries, total_pages)
    print(f'Generated {len(pairs)} qa_pairs')

    q_sections, a_sections, _ = extract_sections(entries)
    print(f'Question sections: {len(q_sections)}, Answer sections: {len(a_sections)}')
    missing = [p['topic_title'] for p in pairs if p['ans_entry'] is None]
    if missing:
        print(f'Warning: {len(missing)} sections without answer: {missing}')

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    out_data = {'total_pages': total_pages, 'qa_pairs': pairs}
    Path(output).write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {output}')

    for p in pairs[:5]:
        print(p['topic_title'], 'q_start=', p['q_start'], 'a_start=', p['a_start'], 'q_end=', p['q_end'])


if __name__ == '__main__':
    main()
