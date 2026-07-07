#!/usr/bin/env python3
"""
合并 data.js + index.html → 单个 index-standalone.html
这样用户双击就能打开，不需要 HTTP server。
"""
import json
from pathlib import Path

INDEX_HTML = Path('math-bank/index.html')
DATA_JS = Path('math-bank/data.js')
OUT = Path('math-bank/数据结构题库.html')

INDEX_HTML = Path('math-bank/index.html')
DATA_JS = Path('math-bank/data.js')
OUT = Path('math-bank/数据结构题库.html')


def main():
    if not INDEX_HTML.exists():
        print(f'ERROR: {INDEX_HTML} missing')
        return
    if not DATA_JS.exists():
        print(f'ERROR: {DATA_JS} missing')
        return

    html = INDEX_HTML.read_text(encoding='utf-8')
    data_js = DATA_JS.read_text(encoding='utf-8')

    # 用 <script> 块替换 <script src="data.js"></script>
    html = html.replace(
        '<script src="data.js"></script>',
        '<script>\n' + data_js + '\n</script>'
    )

    OUT.write_text(html, encoding='utf-8')
    print(f'Wrote {OUT}, {OUT.stat().st_size} bytes ({OUT.stat().st_size / 1024:.1f} KB)')


if __name__ == '__main__':
    main()
