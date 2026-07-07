#!/usr/bin/env python3
"""
合并多门课程的 reshaped questions.json：
  1. 生成总 questions_all.json（兼容旧流程）
  2. 为 math-bank 生成每门课程的独立 data-<key>.js，支持按课程懒加载
  3. 生成 math-bank/data.js 加载器（课程列表 + loadCourseData 函数）

课程 key 约定：
  ds  -> 数据结构
  coa -> 计算机组成原理
  net -> 计算机网络
  os  -> 操作系统
"""
import json
import sys
from pathlib import Path

COURSE_NAME_BY_FILE = {
    'questions.json':     ('数据结构', 'ds'),
    'questions_coa.json': ('组成原理', 'coa'),
    'questions_net.json': ('计算机网络', 'net'),
    'questions_os.json':  ('操作系统', 'os'),
}

COURSE_LONG_BY_FILE = {
    'questions.json':     '数据结构',
    'questions_coa.json': '计算机组成原理',
    'questions_net.json': '计算机网络',
    'questions_os.json':  '操作系统',
}


def write_js_var(dst, var_name, data):
    """把 Python 字典写成 JS 全局变量文件。"""
    pretty = json.dumps(data, ensure_ascii=False, indent=2)
    header = '// Auto-generated — do not edit by hand.\n'
    body = f'window.{var_name} = {pretty};\n'
    dst.write_text(header + body, encoding='utf-8')
    print(f'  [write] {dst}: {dst.stat().st_size / 1024 / 1024:.2f} MB')


def main():
    if len(sys.argv) < 2:
        print('Usage: merge_courses.py <output_questions.json>')
        sys.exit(1)
    out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 自动按固定顺序找输入
    input_files = [
        ('数据结构',    'questions.json'),
        ('计算机组成原理', 'questions_coa.json'),
        ('计算机网络',  'questions_net.json'),
        ('操作系统',    'questions_os.json'),
    ]
    course_data = []
    summary = []
    for course_long, fname in input_files:
        path = Path(fname)
        if not path.exists():
            print(f'  [skip] {fname}: 不存在')
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        chapters = data.get('chapters', [])
        for ch in chapters:
            ch['course'] = course_long  # 给每个 chapter 注入课程名
        short, key = COURSE_NAME_BY_FILE.get(fname, (course_long, course_long))
        course_data.append({
            'course': course_long,
            'short': short,
            'key': key,
            'total_questions': data.get('total_questions', 0),
            'chapters': chapters,
        })
        summary.append((course_long, len(chapters), data.get('total_questions', 0)))
        print(f'  [load] {fname}: {len(chapters)} chapters, {data.get("total_questions",0)} 题')

    # 合并到单个 data 字典
    all_chapters = []
    for cd in course_data:
        for ch in cd['chapters']:
            all_chapters.append(ch)

    out = {
        'title': '王道 408 考研精选题库',
        'courses': [
            {'name': cd['course'], 'short': cd['short'], 'chapter_count': len(cd['chapters']),
             'question_count': cd['total_questions']}
            for cd in course_data
        ],
        'total_questions': sum(cd['total_questions'] for cd in course_data),
        'chapters': all_chapters,
    }

    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n已合并 {len(course_data)} 门课,共 {out["total_questions"]} 题')
    for c, n_ch, n_q in summary:
        print(f'  - {c}: {n_ch} 节, {n_q} 题')

    # 生成 math-bank 懒加载文件
    bank_dir = Path('math-bank')
    bank_dir.mkdir(parents=True, exist_ok=True)

    course_manifest = []
    for cd in course_data:
        key = cd['key']
        var_name = f'QUESTION_BANK_{key.upper()}'
        file_name = f'data-{key}.js'
        course_obj = {
            'title': f'27王道《{cd["course"]}》高清带书签题库',
            'courses': [{'name': cd['course'], 'short': cd['short'],
                         'chapter_count': len(cd['chapters']),
                         'question_count': cd['total_questions']}],
            'total_questions': cd['total_questions'],
            'chapters': cd['chapters'],
        }
        write_js_var(bank_dir / file_name, var_name, course_obj)
        course_manifest.append({
            'name': cd['course'],
            'short': cd['short'],
            'key': key,
            'file': file_name,
            'var': var_name,
            'chapter_count': len(cd['chapters']),
            'question_count': cd['total_questions'],
        })

    loader = bank_dir / 'data.js'
    loader_src = '''// Auto-generated — do not edit by hand.
window.__COURSE_MANIFEST__ = {manifest};

window.loadCourseData = function(courseName) {{
  const info = window.__COURSE_MANIFEST__.find(c => c.name === courseName);
  if (!info) return Promise.reject(new Error('Unknown course: ' + courseName));
  if (window[info.var]) return Promise.resolve(window[info.var]);
  return new Promise((resolve, reject) => {{
    const s = document.createElement('script');
    s.src = info.file;
    s.onload = () => resolve(window[info.var]);
    s.onerror = () => reject(new Error('Failed to load ' + info.file));
    document.head.appendChild(s);
  }});
}};

window.getCourseList = function() {{
  return window.__COURSE_MANIFEST__.map(c => ({{ name: c.name, short: c.short, question_count: c.question_count }}));
}};
'''.format(manifest=json.dumps(course_manifest, ensure_ascii=False, indent=2))
    loader.write_text(loader_src, encoding='utf-8')
    print(f'  [write] {loader}')


if __name__ == '__main__':
    main()
