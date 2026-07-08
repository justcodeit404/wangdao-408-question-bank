#!/usr/bin/env python3
"""
通用版 OCR 流水线：
- 输入：<pdf_path> <qa_pairs_json> <ocr_dir> <images_dir>
- 读 qa_pairs.json, 对每对 (q_start..a_start-1) 和 (a_start..下一对 q_start-1) 范围内的页面做 OCR
- 输出：<ocr_dir>/page_NNN.json

复用 pdf_images/ 全局目录（已存在 page_NNN.png）
"""
import json
import sys
from pathlib import Path
from rapidocr_onnxruntime import RapidOCR


def main():
    if len(sys.argv) < 5:
        print('Usage: python scripts/run_ocr.py <qa_pairs_json> <ocr_dir> <images_dir> <max_pages_label>')
        sys.exit(1)
    qa_json = sys.argv[1]
    ocr_dir = Path(sys.argv[2])
    img_dir = Path(sys.argv[3])
    # 第 4 个参数仅用于日志标签
    label = sys.argv[4]

    ocr_dir.mkdir(parents=True, exist_ok=True)
    engine = RapidOCR()
    data = json.load(open(qa_json, encoding='utf-8'))
    qa = data['qa_pairs']
    total_pages = data['total_pages']

    pages_to_ocr = set()
    for i, q in enumerate(qa):
        q_start = q['q_start']
        a_start = q['a_start']
        if i + 1 < len(qa):
            next_q_start = qa[i + 1]['q_start']
            end = next_q_start - 1
        else:
            end = total_pages
        if a_start:
            for p in range(q_start, a_start):
                pages_to_ocr.add(p)
            for p in range(a_start, end + 1):
                if p >= a_start:
                    pages_to_ocr.add(p)
        else:
            # 没有答案：就 OCR q_start 到下一对 q_start 之前
            for p in range(q_start, end + 1):
                pages_to_ocr.add(p)

    sorted_pages = sorted(pages_to_ocr)
    print(f'[{label}] 待OCR {len(sorted_pages)} 页, 范围 {sorted_pages[0]}-{sorted_pages[-1]}')

    existing = {int(p.stem.split('_')[1]) for p in ocr_dir.glob('page_*.json')}
    todo = [p for p in sorted_pages if p not in existing]
    print(f'[{label}] 已完成 {len(existing)}, 剩余 {len(todo)}')

    for idx, page_num in enumerate(todo):
        img_path = img_dir / f'page_{page_num:03d}.png'
        if not img_path.exists():
            print(f'[{label}] [!] 缺失 {img_path}')
            continue
        try:
            result, _ = engine(str(img_path))
            blocks = []
            if result:
                for box, text, score in result:
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    blocks.append({
                        'text': text,
                        'score': round(float(score), 3),
                        'x0': min(xs), 'y0': min(ys), 'x1': max(xs), 'y1': max(ys),
                    })
            out = {'page': page_num, 'blocks': blocks}
            with open(ocr_dir / f'page_{page_num:03d}.json', 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f'[{label}] [!] page {page_num} 失败: {e}')
        if (idx + 1) % 20 == 0:
            print(f'  [{label}] [{idx + 1}/{len(todo)}] last: page {page_num}')

    print(f'[{label}] OCR 完成,共处理 {len(todo)} 页')


if __name__ == '__main__':
    main()
