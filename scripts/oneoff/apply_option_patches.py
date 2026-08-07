#!/usr/bin/env python3
"""人工核对后的选项补丁批量应用。

输入：tmp/manual_option_patches.json
格式：[
  {"course": "数据结构", "qid": "X15", "page": 46, "options": {"C": "...", "D": "..."}},
  ...
]
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
PATCH_JSON = ROOT / 'tmp' / 'manual_option_patches.json'

COURSES = {
    '数据结构': ROOT / 'output' / 'questions.json',
    '计算机组成原理': ROOT / 'output' / 'questions_coa.json',
    '计算机网络': ROOT / 'output' / 'questions_net.json',
    '操作系统': ROOT / 'output' / 'questions_os.json',
}


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def find_question(data, qid, page):
    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            if q.get('id') == qid and q.get('page') == page:
                return q
    return None


def main():
    patch_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PATCH_JSON
    if not patch_path.exists():
        print(f'[error] 找不到 {patch_path}')
        sys.exit(1)
    patches = load_json(patch_path)
    course_data = {name: load_json(path) for name, path in COURSES.items()}
    applied = 0
    for p in patches:
        name = p['course']
        qid = p['qid']
        page = p['page']
        new_opts = p['options']
        q = find_question(course_data[name], qid, page)
        if not q:
            print(f'  [skip] 找不到 {name} {qid} page {page}')
            continue
        options = q.get('options') or {}
        options.update(new_opts)
        q['options'] = options
        applied += 1
        print(f'  [patched] {name} {qid} page {page}: {new_opts}')
    for name, data in course_data.items():
        save_json(COURSES[name], data)
        print(f'[write] {COURSES[name]}')
    print(f'\n[summary] applied {applied}/{len(patches)} patches')


if __name__ == '__main__':
    main()
