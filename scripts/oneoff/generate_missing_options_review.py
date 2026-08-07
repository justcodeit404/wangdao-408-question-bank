#!/usr/bin/env python3
"""生成缺失选项人工核对 HTML 报告。

输入：tmp/missing_options_fix_report.json
输出：tmp/missing_options_review.html
"""
import json
import html
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
REPORT_JSON = ROOT / 'tmp' / 'missing_options_fix_report.json'
OUT_HTML = ROOT / 'tmp' / 'missing_options_review.html'


def main():
    if not REPORT_JSON.exists():
        print(f'[error] 找不到 {REPORT_JSON}')
        sys.exit(1)
    report = json.loads(REPORT_JSON.read_text(encoding='utf-8'))
    unresolved = report.get('unresolved', [])
    skipped = report.get('skipped_no_bbox', [])

    rows = []
    for r in unresolved:
        item = r.get('item', [])
        if len(item) < 4:
            continue
        qid, page, present, section = item
        missing = [l for l in 'ABCD' if l not in present]
        crop = r.get('crop', '')
        ocr_lines = r.get('ocr_lines', [])
        rows.append({
            'course': '?',
            'qid': qid,
            'page': page,
            'section': section,
            'present': ', '.join(present),
            'missing': ', '.join(missing),
            'crop': crop,
            'ocr': '<br>'.join(html.escape(l) for l in ocr_lines),
        })
    for item in skipped:
        if len(item) < 4:
            continue
        qid, page, present, section = item
        missing = [l for l in 'ABCD' if l not in present]
        rows.append({
            'course': '?',
            'qid': qid,
            'page': page,
            'section': section,
            'present': ', '.join(present),
            'missing': ', '.join(missing),
            'crop': '',
            'ocr': '无 bbox',
        })

    trs = []
    for i, row in enumerate(rows, 1):
        img_tag = f'<img src="{row["crop"]}" style="max-width:600px;max-height:400px;border:1px solid #555;">' if row['crop'] else '无截图'
        trs.append(f'''<tr>
<td>{i}</td>
<td>{html.escape(row["qid"])}<br>第 {row["page"]} 页</td>
<td>{html.escape(row["section"])}</td>
<td>已有: {html.escape(row["present"])}<br>缺失: <b>{html.escape(row["missing"])}</b></td>
<td>{img_tag}</td>
<td style="font-family:monospace;white-space:pre-line;">{row["ocr"]}</td>
</tr>''')

    html_doc = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>缺失选项人工核对</title>
<style>
body {{ font-family: sans-serif; background:#1a1a2e; color:#eee; padding:20px; }}
table {{ border-collapse: collapse; width:100%; }}
th, td {{ border:1px solid #444; padding:8px; text-align:left; vertical-align:top; }}
th {{ background:#2d2d44; }}
tr:nth-child(even) {{ background:#222233; }}
img {{ display:block; margin:4px 0; }}
</style>
</head>
<body>
<h1>缺失选项人工核对（共 {len(rows)} 道）</h1>
<table>
<tr><th>#</th><th>题号/页码</th><th>章节</th><th>选项情况</th><th>题目截图</th><th>OCR 结果</th></tr>
{''.join(trs)}
</table>
</body>
</html>'''

    OUT_HTML.write_text(html_doc, encoding='utf-8')
    print(f'[write] {OUT_HTML} ({len(rows)} 道)')


if __name__ == '__main__':
    main()
