#!/usr/bin/env python3
"""
生成人工补全清单 correction_list.html：
  - 按课程、章节分组
  - 列出无答案题和选择题缺 choice 题
  - 提供查看原题页、答案页的链接
  - 显示题干/解析预览，方便对照 PDF 补全
"""
import json
import html as html_mod
from pathlib import Path
from collections import defaultdict

COURSES = [
    ('数据结构', 'output/questions.json', 'assets/pdf_images/ds'),
    ('计算机组成原理', 'output/questions_coa.json', 'assets/pdf_images/coa'),
    ('计算机网络', 'output/questions_net.json', 'assets/pdf_images/net'),
    ('操作系统', 'output/questions_os.json', 'assets/pdf_images/os'),
]


def img_path(img_dir, page):
    return f'{img_dir}/page_{page:03d}.png'


def needs_fix(q):
    ans = q.get('answer') or {}
    if not ans or not (ans.get('choice') or ans.get('explanation')):
        return True
    if q.get('type') == '选择题' and not ans.get('choice'):
        return True
    return False


def build_html():
    rows = []
    total = 0
    for course_name, fn, img_dir in COURSES:
        if not Path(fn).exists():
            continue
        data = json.load(open(fn, encoding='utf-8'))
        by_chapter = defaultdict(list)
        for ch in data.get('chapters', []):
            ch_name = ch.get('name') or ch.get('topic_title', '未知章节')
            for q in ch.get('questions', []):
                if needs_fix(q):
                    by_chapter[ch_name].append(q)
                    total += 1
        if not by_chapter:
            continue

        rows.append(f'<h2>{html_mod.escape(course_name)}</h2>')
        for ch_name, qs in sorted(by_chapter.items()):
            rows.append(f'<h3>{html_mod.escape(ch_name)} <span class="count">{len(qs)} 道</span></h3>')
            rows.append('<table><thead><tr><th>ID</th><th>题型</th><th>页码</th><th>题干预览</th><th>操作</th></tr></thead><tbody>')
            for q in qs:
                qid = html_mod.escape(q.get('id', '?'))
                qtype = html_mod.escape(q.get('type', '?'))
                page = q.get('page') or '?'
                preview = html_mod.escape(q.get('content', '')[:120])
                ans = q.get('answer') or {}
                ans_preview = html_mod.escape((ans.get('explanation') or '')[:120])
                if ans_preview:
                    preview += f'<br><span class="ans-preview">现有解析：{ans_preview}</span>'
                a_pages = q.get('a_pages', [])
                a_links = ' '.join(
                    f'<a class="link" href="{img_path(img_dir, p)}" target="_blank">答{p}</a>'
                    for p in a_pages[:4]
                )
                q_link = f'<a class="link" href="{img_path(img_dir, page)}" target="_blank">原题页</a>' if isinstance(page, int) else ''
                rows.append(f'<tr><td>{qid}</td><td>{qtype}</td><td>{page}</td><td>{preview}</td><td>{q_link} {a_links}</td></tr>')
            rows.append('</tbody></table>')

    body = '\n'.join(rows)
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>408 题库待补全答案清单</title>
<style>
:root {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif; }}
body {{ max-width: 1100px; margin: 0 auto; padding: 24px; background: #f8fafc; color: #1e293b; }}
h1 {{ font-size: 1.6rem; margin-bottom: 8px; }}
h2 {{ font-size: 1.25rem; margin-top: 32px; color: #4338ca; border-bottom: 2px solid #e0e7ff; padding-bottom: 6px; }}
h3 {{ font-size: 1rem; margin-top: 20px; color: #334155; }}
.count {{ font-size: 0.85rem; color: #64748b; font-weight: 500; margin-left: 8px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0 24px; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgb(15 23 42 / 0.06); }}
th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 0.9rem; vertical-align: top; }}
th {{ background: #f1f5f9; font-weight: 600; color: #475569; }}
tr:hover {{ background: #f8fafc; }}
td:first-child {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-weight: 600; color: #4338ca; white-space: nowrap; }}
td:nth-child(2) {{ white-space: nowrap; }}
td:nth-child(3) {{ white-space: nowrap; }}
td:nth-child(4) {{ color: #334155; line-height: 1.5; }}
.ans-preview {{ display: block; margin-top: 6px; color: #64748b; font-size: 0.85rem; }}
.link {{ display: inline-block; margin: 2px 4px 2px 0; padding: 3px 8px; background: #eef2ff; color: #4f46e5; border-radius: 999px; font-size: 0.78rem; text-decoration: none; }}
.link:hover {{ background: #e0e7ff; }}
.summary {{ background: #fff; padding: 16px; border-radius: 10px; box-shadow: 0 1px 3px rgb(15 23 42 / 0.06); margin-bottom: 24px; }}
</style>
</head>
<body>
<h1>408 题库待补全答案清单</h1>
<div class="summary">共 <strong>{total}</strong> 道题需要补答案或补正确选项。点击“原题页”“答N”可查看对应 PNG 截图。</div>
{body}
</body>
</html>
'''
    out_path = Path('output/reports/correction_list.html')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
    print(f'已生成 {out_path}，共 {total} 道题待补全')


if __name__ == '__main__':
    build_html()
