#!/usr/bin/env python3
"""
补全缺失的解答题答案。
思路：
1. 从题干页 OCR 中解析该题在书中的印刷题号。
2. 根据印刷题号在答案页 OCR 中定位 "XX.【解答】" / "XX.【解析】"。
3. 提取该 heading 之后到下一个 heading 之前的全部文本作为答案。
"""
import json
import re
from pathlib import Path
from rapidocr_onnxruntime import RapidOCR

COURSES = [
    ('数据结构', 'output/questions.json', 'data/ocr/ds', 'assets/pdf_images/ds'),
    ('计算机组成原理', 'output/questions_coa.json', 'data/ocr/coa', 'assets/pdf_images/coa'),
    ('计算机网络', 'output/questions_net.json', 'data/ocr/net', 'assets/pdf_images/net'),
    ('操作系统', 'output/questions_os.json', 'data/ocr/os', 'assets/pdf_images/os'),
]

OCR = RapidOCR()


def ocr_page_to_blocks(img_path):
    result, _ = OCR(str(img_path))
    blocks = []
    if not result:
        return blocks
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        blocks.append({
            'text': text,
            'score': round(float(score), 3),
            'x0': min(xs), 'y0': min(ys),
            'x1': max(xs), 'y1': max(ys),
        })
    blocks.sort(key=lambda b: (b['y0'], b['x0']))
    return blocks


def save_ocr(ocr_dir, page_num, blocks):
    Path(ocr_dir).mkdir(parents=True, exist_ok=True)
    out = {'page': page_num, 'blocks': blocks}
    path = Path(ocr_dir) / f'page_{page_num:03d}.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def load_ocr(ocr_dir, page_num):
    path = Path(ocr_dir) / f'page_{page_num:03d}.json'
    if not path.exists():
        return []
    data = json.load(open(path, encoding='utf-8'))
    blocks = data.get('blocks', [])
    blocks.sort(key=lambda b: (b.get('y0', 0), b.get('x0', 0)))
    return blocks


HEADING_RE = re.compile(r'^\s*(\d{1,2})\s*[\.．、]?\s*[【\[]?(解答|解析)[】\]]?\s*(.*)$')
NUM_PREFIX_RE = re.compile(r'^\s*(\d{1,2})\s*[\.．、]')


def find_printed_number(q, ocr_dir):
    """在题干页 OCR 中，根据 bbox 找到该题印刷题号。"""
    page = q['page']
    bbox = q.get('bbox') or []
    if not bbox:
        return None
    qy0, qy1 = bbox[1], bbox[3]
    blocks = load_ocr(ocr_dir, page)
    candidates = []
    for b in blocks:
        by0, by1 = b['y0'], b['y1']
        # 与题干区域有垂直重叠
        if by1 < qy0 - 20 or by0 > qy1 + 20:
            continue
        m = NUM_PREFIX_RE.match(b['text'])
        if not m:
            continue
        num = int(m.group(1))
        # 印刷题号通常不会超过 50
        if num > 50:
            continue
        # 要求数字后面紧跟题号后的内容，避免截断到年份/大数
        # 这里用 y0 与题干顶部的距离来排序，最靠近题干顶部的即为题号行
        candidates.append((abs(by0 - qy0), num, b['text']))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def find_answer_blocks(blocks, printed_num):
    """在已排序的 blocks 中定位 heading 并返回 heading 及其后到下一个 heading 的 blocks。
    heading 行中若带有子问号（如 "17.【解答】1）"），也计入答案内容。
    """
    start_idx = None
    first_rest = ''
    for i, b in enumerate(blocks):
        m = HEADING_RE.match(b['text'])
        if m and int(m.group(1)) == printed_num:
            start_idx = i
            first_rest = m.group(3) or ''
            break
    if start_idx is None:
        return None
    end_idx = len(blocks)
    for j in range(start_idx + 1, len(blocks)):
        m = HEADING_RE.match(blocks[j]['text'])
        if m:
            end_idx = j
            break
    result_blocks = blocks[start_idx:end_idx]
    # 把 heading 行剩下的文本作为第一个内容块
    if first_rest:
        result_blocks = [dict(result_blocks[0], text=first_rest)] + result_blocks[1:]
    return result_blocks


def extract_answer_for(q, ocr_dir, img_dir):
    printed_num = find_printed_number(q, ocr_dir)
    if not printed_num:
        return None, 'no_printed_num'
    a_pages = q.get('a_pages', [])
    if not a_pages:
        return None, 'no_a_pages'
    # 重新 OCR 答案页（覆盖旧文件，旧文件有编码损坏）
    for p in a_pages:
        img_path = Path(img_dir) / f'page_{p:03d}.png'
        if not img_path.exists():
            continue
        blocks = ocr_page_to_blocks(img_path)
        save_ocr(ocr_dir, p, blocks)
    # 加载并合并所有答案页 blocks
    all_blocks = []
    for p in a_pages:
        blocks = load_ocr(ocr_dir, p)
        for b in blocks:
            b['_page'] = p
        all_blocks.extend(blocks)
    ans_blocks = find_answer_blocks(all_blocks, printed_num)
    if ans_blocks is None:
        return None, f'heading_not_found_for_num_{printed_num}'
    explanation = '\n'.join(b['text'] for b in ans_blocks).strip()
    if not explanation:
        return None, 'empty_explanation'
    return {'choice': None, 'explanation': explanation}, 'ok'


def main():
    total_fixed = 0
    for course_name, qfn, ocr_dir, img_dir in COURSES:
        if not Path(qfn).exists():
            continue
        data = json.load(open(qfn, encoding='utf-8'))
        fixed = 0
        for ch in data.get('chapters', []):
            for q in ch.get('questions', []):
                if q.get('type') == '选择题':
                    continue
                if q.get('answer'):
                    continue
                new_ans, reason = extract_answer_for(q, ocr_dir, img_dir)
                if new_ans:
                    q['answer'] = new_ans
                    fixed += 1
                    print(f'[{course_name}] {q["id"]} p{q["page"]} 已补全')
                else:
                    print(f'[{course_name}] {q["id"]} p{q["page"]} 未补全: {reason}')
        if fixed > 0:
            Path(qfn).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'{course_name}: 补全 {fixed} 道题')
            total_fixed += fixed
        else:
            print(f'{course_name}: 未补全')
    print(f'总计补全: {total_fixed}')


if __name__ == '__main__':
    main()
