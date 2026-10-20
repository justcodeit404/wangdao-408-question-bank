#!/usr/bin/env python3
"""合并多门课程的 reshaped questions.json：
  1. 生成总 questions_all.json（兼容旧流程）
  2. 为 math-bank 生成每门课程的独立 data-<key>.json，支持按课程懒加载
  3. 生成 math-bank/data.js 加载器（课程列表 + loadCourseData 函数）

课程 key 约定（顺序即前端课程 tab 展示顺序）：
  ds  -> 数据结构
  coa -> 计算机组成原理
  os  -> 操作系统
  net -> 计算机网络
"""
import json
import sys
from pathlib import Path

from config import COURSES, MATH_BANK_DIR
from utils import write_json_with_gz_atomic, write_text_atomic

sys.stdout.reconfigure(encoding='utf-8')

# 真题增补：2026 统考真题（官方原卷 + 官方答案），按章节追加进对应课程。
# 源文件在 data/zhenti/<年份>.json；merge_courses 每次重建都会重新追加，
# 因此不受 output/questions_*.json 重抽影响，也不改动原书题目。
ZHENTI_DIR = Path(__file__).resolve().parent.parent / 'data' / 'zhenti'


def load_curated() -> list[tuple[str, dict, dict]]:
    rows: list[tuple[str, dict, dict]] = []
    if not ZHENTI_DIR.is_dir():
        return rows
    for path in sorted(ZHENTI_DIR.glob('*.json')):
        payload = json.loads(path.read_text(encoding='utf-8'))
        meta = payload.get('meta') or {}
        for item in payload.get('items') or []:
            rows.append((path.stem, meta, item))
    return rows


def append_curated(course_key: str, chapters: list[dict], curated: list[tuple[str, dict, dict]]) -> int:
    by_name = {ch['name']: ch for ch in chapters}
    added = 0
    for stem, meta, item in curated:
        if item.get('course') != course_key:
            continue
        chapter = by_name.get(item.get('chapter'))
        if chapter is None:
            raise SystemExit(f'[curated] {stem}: chapter not found: {item.get("chapter")}')
        qid = str(item.get('id') or '').strip()
        if not qid:
            raise SystemExit(f'[curated] {stem}: missing id for {item.get("chapter")}')
        if any(str(q.get('id')) == qid for q in chapter.get('questions') or []):
            raise SystemExit(f'[curated] {stem}: duplicate id {qid} in {item.get("chapter")}')
        year = meta.get('year')
        image = item.get('image')
        source_label = meta.get('source_label') or f'{year} 统考真题'
        source_kind = meta.get('source_kind') or 'official'
        chapter.setdefault('questions', []).append({
            'id': qid,
            'type': item.get('type') or '选择题',
            'content': item.get('content') or '',
            'options': item.get('options') or None,
            'sub_questions': None,
            'page': None,
            'bbox': None,
            'has_image': bool(image),
            'image_ref': {'cropped': image, 'note': f'{year} 统考真题题图'} if image else None,
            'topic_title': f'{year} 统考真题',
            'answer': {
                'choice': item.get('choice') or '',
                'explanation': item.get('explanation') or '',
            },
            'q_pages': [],
            'a_pages': [],
            'source_label': source_label,
            'curated': {
                'year': year,
                'source': source_kind,
                'sources': [s.get('url') for s in (meta.get('sources') or [])],
            },
        })
        chapter['question_count'] = len(chapter['questions'])
        added += 1
    return added



def write_json(dst, data):
    """把 Python 字典原子写入紧凑 JSON 文件，并打印大小。

    同时原子生成 .gz 预压缩文件，供服务器直接返回，避免每次请求都实时压缩。
    """
    compact = write_json_with_gz_atomic(dst, data, ensure_ascii=False)
    gz_dst = Path(str(dst) + '.gz')
    print(f'  [write] {dst}: {dst.stat().st_size / 1024 / 1024:.2f} MB '
          f'({gz_dst.stat().st_size / 1024 / 1024:.2f} MB gz)')


def escape_script_tag(s):
    """对嵌入 <script> 标签的 JSON 文本转义 </script>，防止提前闭合脚本。"""
    return s.replace('</script>', '<\\/script>')


# 与 math-bank/choice-only.js isChoiceQuestionType 对齐。
# viewer 只展示选择题（加载层过滤），data.js manifest 的 question_count 必须
# 烘焙选择题口径，否则未加载科目的课程 tab 会显示含解答题的原始总题数。
_CHOICE_TYPES = frozenset({
    'single_choice', 'multiple_choice', 'ordered_choice', '选择题',
    'multiple', 'multi', 'single', '单选', '多选',
})


def _is_choice_type(t):
    t = str(t or '').strip()
    if not t:
        return False
    low = t.lower()
    if t in _CHOICE_TYPES or low in _CHOICE_TYPES:
        return True
    if '选择' in t and '解答' not in t:
        return True
    if low == 'choice' or low.endswith('_choice') or low.endswith('choice'):
        if low.count('choice') == 1 and len(low) <= 32:
            return True
    return False


def _choice_total(chapters):
    return sum(1 for ch in chapters for q in ch.get('questions', [])
               if _is_choice_type(q.get('type')))


def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/merge_courses.py output/questions_all.json')
        sys.exit(1)
    out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    course_data = []
    summary = []
    curated = load_curated()
    for c in COURSES:
        path = Path(c.out_json)
        if not path.exists():
            print(f'  [skip] {c.out_json}: 不存在')
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        chapters = data.get('chapters', [])
        for ch in chapters:
            ch['course'] = c.name  # 给每个 chapter 注入课程名
        added = append_curated(c.key, chapters, curated)
        if added:
            print(f'  [curated] {c.key}: 追加统考真题 {added} 题')
        total = data.get('total_questions', 0) + added
        course_data.append({
            'course': c.name,
            'short': c.short,
            'key': c.key,
            'total_questions': total,
            'chapters': chapters,
        })
        summary.append((c.name, len(chapters), total))
        print(f'  [load] {c.out_json}: {len(chapters)} chapters, {total} 题')

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

    write_json_with_gz_atomic(out_path, out, ensure_ascii=False)
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
            course_name=escape_script_tag(json.dumps(cd['course'], ensure_ascii=False)),
            data=escape_script_tag(json.dumps(course_obj, ensure_ascii=False, separators=(',', ':')))
        )
        write_text_atomic(bank_dir / js_file_name, js_wrapper, encoding='utf-8')
        print(f'  [write] {bank_dir / js_file_name}')

        course_manifest.append({
            'name': cd['course'],
            'short': cd['short'],
            'key': key,
            'file': file_name,
            'js_file': js_file_name,
            'chapter_count': len(cd['chapters']),
            'question_count': _choice_total(cd['chapters']),
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
'''.format(manifest=escape_script_tag(json.dumps(course_manifest, ensure_ascii=False, indent=2)))
    write_text_atomic(loader, loader_src, encoding='utf-8')
    print(f'  [write] {loader}')


if __name__ == '__main__':
    main()
