#!/usr/bin/env python3
"""
将 questions.json 转成 math-bank/data.js，包含 images/路径处理
"""
import json
from pathlib import Path
import sys


def main():
    if len(sys.argv) != 3:
        print("Usage: build_data_js.py questions.json data.js")
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_text(encoding='utf-8')
    data = json.loads(raw)
    pretty = json.dumps(data, ensure_ascii=False, indent=2)
    header = '// Auto-generated — do not edit by hand.\n'
    body = 'const QUESTION_BANK = ' + pretty + ';\n'
    dst.write_text(header + body, encoding='utf-8')
    print('Wrote', dst, dst.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
