#!/usr/bin/env python3
"""修正 OCR 把罗马数字 III 错识别成 IIII / IIIIl / IIl 等问题。

直接修改输出 questions_*.json，然后应运行 merge_courses.py 重新生成 math-bank 懒加载文件。
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    ROOT / 'output/questions.json',
    ROOT / 'output/questions_coa.json',
    ROOT / 'output/questions_net.json',
    ROOT / 'output/questions_os.json',
]

PATTERNS = [
    (re.compile(r'I{4,}'), 'III'),   # 4 个及以上 I 统一归并为 III
    (re.compile(r'III[lL]'), 'III'), # III 后带 l/L
    (re.compile(r'IIl'), 'III'),     # II 后带 l
]


def fix_text(text: str) -> str:
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text


def walk_and_fix(obj):
    if isinstance(obj, dict):
        return {k: walk_and_fix(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk_and_fix(v) for v in obj]
    if isinstance(obj, str):
        return fix_text(obj)
    return obj


def main():
    for path in FILES:
        if not path.exists():
            print(f'[skip] {path} 不存在')
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        fixed = walk_and_fix(data)
        path.write_text(json.dumps(fixed, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        print(f'[fixed] {path}')


if __name__ == '__main__':
    main()
