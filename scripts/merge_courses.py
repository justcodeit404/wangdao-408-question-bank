#!/usr/bin/env python3
"""合并多门课程的 reshaped questions.json：
  1. 生成总 questions_all.json（兼容旧流程）
  2. 为 math-bank 生成每门课程的独立 data-<key>.json，支持按课程懒加载
  3. 生成 math-bank/data.js 加载器（课程列表 + loadCourseData 函数）

课程 key 约定：
  ds  -> 数据结构
  coa -> 计算机组成原理
  net -> 计算机网络
  os  -> 操作系统
"""
import gzip
import json
import sys
from pathlib import Path

from config import COURSES, MATH_BANK_DIR

sys.stdout.reconfigure(encoding='utf-8')


def write_json(dst, data):
    """把 Python 字典写成紧凑 JSON 文件，并打印大小。

    同时生成 .gz 预压缩文件，供服务器直接返回，避免每次请求都实时压缩。
    """
    compact = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    dst.write_text(compact, encoding='utf-8')
    gz_dst = Path(str(dst) + '.gz')
    gz_dst.write_bytes(gzip.compress(compact.encode('utf-8'), compresslevel=9))
    print(f'  [write] {dst}: {dst.stat().st_size / 1024 / 1024:.2f} MB '
          f'({gz_dst.stat().st_size / 1024 / 1024:.2f} MB gz)')


def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/merge_courses.py output/questions_all.json')
        sys.exit(1)
    out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    course_data = []
    summary = []
    for c in COURSES:
        path = Path(c.out_json)
        if not path.exists():
            print(f'  [skip] {c.out_json}: 不存在')
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        chapters = data.get('chapters', [])
        for ch in chapters:
            ch['course'] = c.name  # 给每个 chapter 注入课程名
        course_data.append({
            'course': c.name,
            'short': c.short,
            'key': c.key,
            'total_questions': data.get('total_questions', 0),
            'chapters': chapters,
        })
        summary.append((c.name, len(chapters), data.get('total_questions', 0)))
        print(f'  [load] {c.out_json}: {len(chapters)} chapters, {data.get("total_questions", 0)} 题')

    # 合并到单个 data 字典
    all_chapters = [ch for cd in course_data for ch in cd['chapters']]

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

    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'\n已合并 {len(course_data)} 门课,共 {out["total_questions"]} 题')
    for c, n_ch, n_q in summary:
        print(f'  - {c}: {n_ch} 节, {n_q} 题')

    # 生成 math-bank 懒加载文件
    bank_dir = MATH_BANK_DIR
    bank_dir.mkdir(parents=True, exist_ok=True)

    course_manifest = []
    for cd in course_data:
        key = cd['key']
        file_name = f'data-{key}.json'
        js_file_name = f'data-{key}.js'
        course_obj = {
            'title': f'27王道《{cd["course"]}》高清带书签题库',
            'courses': [{'name': cd['course'], 'short': cd['short'],
                         'chapter_count': len(cd['chapters']),
                         'question_count': cd['total_questions']}],
            'total_questions': cd['total_questions'],
            'chapters': cd['chapters'],
        }
        write_json(bank_dir / file_name, course_obj)

        # 同时生成 .js 包装文件，用于 file:// 协议直接打开时绕过 fetch CORS 限制
        js_wrapper = '''// Auto-generated — do not edit by hand.
window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {{}};
window.__COURSE_CACHE__[{course_name}] = {data};
'''.format(
            course_name=json.dumps(cd['course'], ensure_ascii=False),
            data=json.dumps(course_obj, ensure_ascii=False, separators=(',', ':'))
        )
        (bank_dir / js_file_name).write_text(js_wrapper, encoding='utf-8')
        print(f'  [write] {bank_dir / js_file_name}')

        course_manifest.append({
            'name': cd['course'],
            'short': cd['short'],
            'key': key,
            'file': file_name,
            'js_file': js_file_name,
            'chapter_count': len(cd['chapters']),
            'question_count': cd['total_questions'],
        })

    loader = bank_dir / 'data.js'
    loader_src = '''// Auto-generated — do not edit by hand.
window.__COURSE_MANIFEST__ = {manifest};
window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {{}};

window.loadCourseData = function(courseName) {{
  const info = window.__COURSE_MANIFEST__.find(c => c.name === courseName);
  if (!info) return Promise.reject(new Error('Unknown course: ' + courseName));
  if (window.__COURSE_CACHE__[courseName]) return Promise.resolve(window.__COURSE_CACHE__[courseName]);

  // file:// 协议下 fetch 本地 JSON 会被浏览器 CORS 拦截，改用 script 标签加载同目录 .js 包装文件
  if (window.location.protocol === 'file:') {{
    return new Promise((resolve, reject) => {{
      const script = document.createElement('script');
      script.src = info.js_file;
      script.onload = () => {{
        if (window.__COURSE_CACHE__[courseName]) resolve(window.__COURSE_CACHE__[courseName]);
        else reject(new Error('Course data not loaded: ' + courseName));
      }};
      script.onerror = () => reject(new Error('Failed to load ' + info.js_file));
      document.head.appendChild(script);
    }});
  }}

  return fetch(info.file)
    .then(r => {{
      if (!r.ok) throw new Error('Failed to load ' + info.file + ': ' + r.status);
      return r.json();
    }})
    .then(data => {{
      window.__COURSE_CACHE__[courseName] = data;
      return data;
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
