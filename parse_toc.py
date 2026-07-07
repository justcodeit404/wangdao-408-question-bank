#!/usr/bin/env python3
"""
通用版 TOC 解析：扫描一个 PDF 的书签，识别所有 本节试题精选/答案与解析 对。
用法：python parse_toc.py <pdf_path> <out_json>
"""
import json
import sys
from pathlib import Path
import fitz


def main():
    if len(sys.argv) < 3:
        print('Usage: python parse_toc.py <pdf_path> <out_json>')
        sys.exit(1)
    pdf_path = sys.argv[1]
    out_json = sys.argv[2]

    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    total_pages = len(doc)
    print(f'PDF总页数: {total_pages}, 书签条目: {len(toc)}')

    # 同时落一份 toc.json（兼容旧用法）
    toc_path = Path(out_json).parent.parent / f'toc_{Path(out_json).stem.replace("_qa_pairs","")}.json'
    with open(toc_path, 'w', encoding='utf-8') as f:
        json.dump(toc, f, ensure_ascii=False, indent=2)
    print(f'已保存 {toc_path}')
    qa_pairs = []
    L3_indices = [i for i, t in enumerate(toc) if t[0] == 3]
    for idx in L3_indices:
        entry = toc[idx]
        title = entry[1]
        start_page = entry[2]
        ans_entry = None
        # 匹配 本节试题精选 / 本节习题精选（不同科目用词不同）
        if '本节试题精选' in title or '本节习题精选' in title:
            for j in range(idx + 1, len(toc)):
                if toc[j][0] == 3:
                    # 下一条 L3 是 答案与解析 / 答案解析
                    if '答案与解析' in toc[j][1] or '答案解析' in toc[j][1]:
                        ans_entry = toc[j]
                    break
        else:
            continue
        q_children = []
        for j in range(idx + 1, len(toc)):
            t = toc[j]
            if t[0] == 3:
                break
            if t[0] == 4:
                q_children.append(t)
        a_children = []
        if ans_entry is not None:
            try:
                ans_idx = toc.index(ans_entry)
            except ValueError:
                ans_idx = -1
            for j in range(ans_idx + 1, len(toc)):
                t = toc[j]
                if t[0] == 3:
                    break
                if t[0] == 4:
                    a_children.append(t)
        qa_pairs.append({
            'topic_title': title,
            'q_start': start_page,
            'q_children': q_children,
            'ans_entry': ans_entry,
            'a_start': ans_entry[2] if ans_entry else None,
            'a_children': a_children,
        })

    print(f'找到 {len(qa_pairs)} 个 题目-答案 对')
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({'total_pages': total_pages, 'qa_pairs': qa_pairs}, f, ensure_ascii=False, indent=2)
    print(f'已保存 {out_json}')
    doc.close()


if __name__ == '__main__':
    main()
