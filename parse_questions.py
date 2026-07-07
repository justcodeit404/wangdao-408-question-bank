#!/usr/bin/env python3
"""
基于OCR结果，将每页文本按"题号+选项+答案"模式切分为每道题。

输入：scripts_output/qa_pairs.json + ocr/page_XXX.json
输出：questions.json

题目格式识别（已验证page 8）：
  01. 题目内容
  A. 选项  B. 选项   (同行多列)
  ...
  02. 题目内容
  ...
选项是横向多列的，所以同一行的A/B/C/D要用列位置区分

答案格式识别（已验证page 9）：
  01. C   ← 单选答案 + 单独段解析
  ...
  二、综合应用题
  01.【解答】
  解析文本...
"""

import json
import re
import sys
from pathlib import Path
from collections import Counter

OCR_DIR = Path('ocr')
QA_JSON = 'scripts_output/qa_pairs.json'
TOC_JSON = 'toc.json'
OUTPUT_JSON = 'questions.json'
COURSE_TITLE = '27王道《数据结构》高清带书签题库'
TOTAL_PAGES = 397


def get_block_text(page_data):
    blocks = page_data.get('blocks', [])
    items = []
    for b in blocks:
        items.append((b['y0'], b['x0'], b['text']))
    items.sort(key=lambda t: (t[0], t[1]))
    return items


# 题号格式: 01. 或 02. …（零填充两位以上），要求开头数字 ≤ 2 位
QUESTION_HEADER_RE = re.compile(r'^\s*0?([1-9]\d?)[\.．、]\s*(.+)$')
# 排除答案短格式: 纯"01. C"，也支持多选/多空答案如 "06. B、D" / "11.B,A" / "16.B、E、C、D"
ANSWER_SHORT_RE = re.compile(r'^\s*0?([1-9]\d?)[\.．、]\s*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)\s*$')
OPTION_LINE_RE = re.compile(r'^([A-Da-d])[\.．、]\s*(.+?)$')


def extract_answer_choice(line):
    """从答案短格式行提取题号和答案字母，兼容 OCR 识别中的带圈数字、中文逗号等变体。
    只匹配题号后紧跟答案字母（允许分隔符）的短格式，避免把题干中的"B树"等误当答案。
    例如：
      11. B      -> ('11', 'B')
      11. B、D   -> ('11', 'BD')
      11.B，A    -> ('11', 'BA')
      11.①B、②D -> ('11', 'BD')
      16.B、E、C、D -> ('16', 'BECD')
    """
    m = re.match(r'^\s*0?([1-9]\d?)[\.．、]', line)
    if not m:
        return None
    qid = m.group(1).zfill(2)
    rest = line[m.end():]
    # 去掉带圈数字前缀（如 ①B 中的 ①）
    rest = re.sub(r'[①-⑨⑩]', '', rest)
    # 匹配开头的答案字母序列，允许用、,，\s 分隔
    choice_part = re.match(r'^\s*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)\s*', rest)
    if not choice_part:
        return None
    letters = re.findall(r'[A-Ga-g]', choice_part.group(1))
    if not letters:
        return None
    return qid, ''.join(letters).upper()
ANS_HEADER_RE = re.compile(r'^\s*0?([1-9]\d?)[\.．、]\s*[\【\[]?解答[\】\]]?\s*$')
APP_ANS_START_RE = re.compile(r'^\s*0?([1-9]\d?)[\.．、]\s*(.+)$')

# 章节/小节标记：必须排除
# - "1.1.3 本节试题精选"
# - "1.2.3  本节试题精选"
# - "1.1.3本节试题精选"  ← 注意有空格也有无空格
# - "2.数据的存储结构"  ← 数字.中文
# - "一、单项选择题"
TOPIC_HEADER_RE = re.compile(r'^\s*\d+(?:\.\d+){1,3}\s')
SECTION_HEADER_RE = re.compile(r'^\s*[一二三四五六七八九十][、．]\s*[一-龥]+')
NUMBER_HEADER_RE = re.compile(r'^\s*\d{1,2}[\.．、]\s*[一-龥□（(]')


def group_to_lines(items, y_tol=6):
    """把items按y聚合成行"""
    lines = []
    cur = None
    for y, x, text in items:
        if cur is None or abs(y - cur['y']) > y_tol:
            if cur is not None:
                lines.append(cur)
            cur = {'y': y, 'items': [(x, text)]}
        else:
            cur['items'].append((x, text))
    if cur is not None:
        lines.append(cur)
    # 每行按x排序
    for ln in lines:
        ln['items'].sort(key=lambda t: t[0])
        ln['texts'] = [t for _, t in ln['items']]
    return lines


def is_question_id(s):
    """判断是否是题号前缀：01. 或 02."""
    return bool(re.match(r'^\s*0?\d{1,2}[\.．、]', s))


def parse_questions_page(page_data, page_w):
    """保留旧接口，但内部调用跨页解析。"""
    return parse_questions_span([page_data], page_w)


def parse_questions_span(page_data_list, page_w):
    """跨多页解析题目。
    关键点：
    - 合并多页 blocks，保持阅读顺序
    - 从第一个「本节试题/习题精选」标题之后开始解析
    - 遇到「答案与解析」标题之后停止解析题目
    - 题号标题行："01. …"
    - 选项行（横向多列）："A. …" + "B. …" + "C. …" + "D. …"
    - 题目之间用下一个题号分隔
    """
    # 合并所有页的 blocks，按页顺序 + 页内 (y, x) 排序
    # 给每页的 y 坐标加上页偏移，避免不同页的 block 混在一起
    all_items = []
    for page_idx, page_data in enumerate(page_data_list):
        y_offset = page_idx * 10000
        for y, x, text in get_block_text(page_data):
            all_items.append((y + y_offset, x, text))
    lines = group_to_lines(all_items)

    # 找到题目区起始位置：第一个「本节试题/习题精选」标题之后
    start_idx = 0
    section_start_re = re.compile(r'^\s*\d+\.\d+(?:\.\d+)?\s*(本节试题精选|本节习题精选)\s*$')
    for i, ln in enumerate(lines):
        joined = ' '.join(ln['texts']).strip()
        if section_start_re.match(joined):
            start_idx = i + 1
            break

    # 找到题目区结束位置：第一个「答案与解析」标题
    end_idx = len(lines)
    answer_header_re = re.compile(r'^\s*\d+\.\d+(?:\.\d+)?\s*答案与解析\s*$')
    for i in range(start_idx, len(lines)):
        joined = ' '.join(lines[i]['texts']).strip()
        if answer_header_re.match(joined):
            end_idx = i
            break

    lines = lines[start_idx:end_idx]

    def is_real_question_header(joined):
        """是否为真正的选择题题号（不是章节标题）
        真正题号特征：零填充如"01."/"02."
        章节标题特征：
          - "2.数据的存储结构" → 单数字如"2."开头，无填充
          - "1.1.3本节试题精选" → 多点
        """
        m = QUESTION_HEADER_RE.match(joined)
        if not m:
            return False
        qid = m.group(1)
        body = m.group(2).strip()
        joined_stripped = joined.lstrip()
        # 单数字1-9开头（无0填充）→ 视为章节子标题，跳过
        # 但需要兼容全/半角点号
        if len(qid) == 1:
            ok = False
            for sep in ('.', '．'):
                if joined_stripped.startswith('0' + qid + sep):
                    ok = True
                    break
            if not ok:
                return False
        # 多点形式 → 章节号
        if not re.match(r'^\s*0?\d{1,2}[\.．]', joined):
            return False
        if len(body) < 2:
            return False
        return True

    questions = []
    cur = None

    def flush():
        nonlocal cur
        if cur is not None:
            # 如果未识别到独立选项行，尝试从题干正文中提取内嵌选项
            if not cur.get('options'):
                inline_opts = extract_inline_options(cur['content'])
                if inline_opts:
                    cur['options'] = inline_opts
                    cur['options_order'] = sorted(inline_opts.keys())
            if cur.get('options'):
                cur['type'] = '选择题'
            else:
                cur['type'] = '综合应用题'
            questions.append(cur)
            cur = None

    i = 0
    while i < len(lines):
        ln = lines[i]
        joined = ' '.join(ln['texts']).strip()
        if not joined:
            i += 1
            continue

        # 跳过章节标题/小节标题
        if TOPIC_HEADER_RE.match(joined) or SECTION_HEADER_RE.match(joined):
            i += 1
            continue

        # 答案短格式 "01. C" - 在题目页里通常不会出现，但容错
        if extract_answer_choice(joined):
            i += 1
            continue

        # 题号+题目
        m = QUESTION_HEADER_RE.match(joined)
        if m and is_real_question_header(joined):
            qid = m.group(1).zfill(2)  # 补零
            body = m.group(2).strip()
            flush()
            cur = {
                'id': qid,
                'content': body,
                'options': {},  # option_letter -> text
                'options_order': [],  # 保持顺序
            }
            i += 1
            # 后续行：要么是选项（同行可能有多个），要么是题目延续
            while i < len(lines):
                ln2 = lines[i]
                joined2 = ' '.join(ln2['texts']).strip()
                if not joined2:
                    i += 1
                    continue
                # 下一个真题号了
                if QUESTION_HEADER_RE.match(joined2) and is_real_question_header(joined2):
                    break
                # 题目页里不该出现的章节标题
                if TOPIC_HEADER_RE.match(joined2) or SECTION_HEADER_RE.match(joined2):
                    break
                # 把这行拆成 [A. xxx] [B. xxx] [C. xxx] [D. xxx]
                cols = split_options_in_row(ln2['texts'])
                if cols:
                    # 全部是选项
                    for letter, text in cols:
                        cur['options'][letter.upper()] = text
                        cur['options_order'].append(letter.upper())
                    i += 1
                else:
                    # 既不是题号也不是选项 = 题文延续
                    cur['content'] += '\n' + joined2
                    i += 1
            continue

        # 选项行（无题号开头）— 通常是单列/单选项
        cols = split_options_in_row(ln['texts'])
        if cols and cur is not None:
            for letter, text in cols:
                cur['options'][letter.upper()] = text
                cur['options_order'].append(letter.upper())
            i += 1
            continue

        # 其他行：可能是题目的延续（无题号情况罕见）
        if cur is not None and not cur['options']:
            cur['content'] += '\n' + joined
        i += 1

    flush()
    return questions


def split_options_in_row(texts):
    """一行里通常有 A.xxx B.xxx C.xxx D.xxx，识别并切分。
    返回 [(letter, text), ...] 若全是选项；否则返回None
    """
    if not texts:
        return None
    if len(texts) == 1:
        t = texts[0]
        # 单文本块可能内嵌多个选项，如 "A. xxx B. xxx C. xxx D. xxx"
        if OPTION_LINE_RE.match(t):
            parts = re.split(r'(?=[A-Da-d][\.．、])', t)
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) >= 2:
                cols = []
                for p in parts:
                    m = OPTION_LINE_RE.match(p)
                    if m:
                        cols.append((m.group(1).upper(), m.group(2)))
                if len(cols) >= 2:
                    return cols
            # 单个选项
            m = OPTION_LINE_RE.match(t)
            return [(m.group(1).upper(), m.group(2))] if m else None
        return None
    cols = []
    for t in texts:
        m = OPTION_LINE_RE.match(t)
        if m:
            cols.append((m.group(1).upper(), m.group(2)))
        else:
            # 跨列文本/不带选项字母开头
            # 检查这个t是否是大块的延续文本，可忽略
            return None if not cols else cols
    # 验证选项数：>=2 且按字母顺序
    if len(cols) >= 2:
        return cols
    if len(cols) == 1:
        return cols
    return None


def extract_inline_options(content):
    """从题干正文中提取内嵌的 A/B/C/D 选项（容错 OCR 把选项合并到题干一行的情况）。
    例如："错误的是（）。 A. xxx B. xxx C. xxx D. xxx"
    返回 {A: text, B: text, ...} 或 None。
    """
    if not content:
        return None
    # 把全角点号统一为半角，便于匹配
    text = content.replace('．', '.')
    # 匹配 A. ... B. ... C. ... D. ...，允许换行
    pattern = r'([A-Da-d])\.\s*(.*?)(?=\s*[A-Da-d]\.\s*|$)'
    matches = list(re.finditer(pattern, text, re.DOTALL))
    if len(matches) < 2:
        return None
    options = {}
    for m in matches:
        letter = m.group(1).upper()
        opt_text = m.group(2).strip().replace('\n', ' ')
        if letter not in options:
            options[letter] = opt_text
    if 'A' in options and 'B' in options:
        return options
    return None


def parse_answer_page(page_data):
    """解析答案区一行：01. C / 解析文字等
    注意：
      - 答案页可能还包含上一组精选题的"二、综合应用题"题目（如果是该题组跨页），
        这部分需要丢弃
      - 第一段是选择题答案，后段是综合应用题答案
    返回: {
      'choice': {id: answer_data},
      'app': {id: answer_data}
    }
    """
    items = get_block_text(page_data)
    lines = group_to_lines(items)

    # 找到"X.Y.Z 答案与解析"位置，从那之后开始是真正的答案区
    ans_start_idx = 0
    ANSWER_HEADER_RE = re.compile(r'^\s*\d+\.\d+(?:\.\d+)?\s*答案与解析')
    for i, ln in enumerate(lines):
        joined = ' '.join(ln['texts']).strip()
        if ANSWER_HEADER_RE.match(joined):
            ans_start_idx = i
            break

    answer_lines = lines[ans_start_idx:]

    choice_answers = {}
    app_answers = {}
    section = 'choice'  # 'choice' or 'app'
    cur = None

    def save_cur():
        """保存当前题到对应section。
        使用 cur 自身记录的 _section，而不是外层可能已失步的 section 变量，
        避免章节标题漏识别时应用题答案被错存到选择题字典。"""
        nonlocal cur
        if cur is not None:
            if cur['explanation']:
                cur['explanation'] = cur['explanation'].strip()
            target = choice_answers if cur.get('_section') == 'choice' else app_answers
            # 不要覆盖同section的现有项（保留先遇到的，通常是选择题短答案）
            if cur['id'] not in target:
                target[cur['id']] = cur
            cur = None

    i = 0
    while i < len(answer_lines):
        ln = answer_lines[i]
        joined = ' '.join(ln['texts']).strip()
        if not joined:
            i += 1
            continue

        # 章节标题：兼容 "一、单项选择题" / "二、综合应用题" 等，
        # 也兼容 OCR 丢失序号只剩 "单项选择题" / "综合应用题" 的情况
        chapter_header_re = re.compile(r'^\s*(?:[一二三四五六七八九十][、．])?\s*(单项选择题|综合应用题|填空题|解答题)')
        m_header = chapter_header_re.match(joined)
        if m_header:
            sec_name = m_header.group(1)
            save_cur()  # 当前题入栈
            section = 'app' if ('综合' in sec_name or '解答' in sec_name or '应用' in sec_name) else 'choice'
            i += 1
            continue

        # 短答案 01. C
        ans_match = extract_answer_choice(joined)
        if ans_match:
            save_cur()
            qid, choice = ans_match
            cur = {'id': qid, 'choice': choice,
                   'explanation': '', '_section': section}
            i += 1
            # 收集解析
            while i < len(answer_lines):
                ln2 = answer_lines[i]
                joined2 = ' '.join(ln2['texts']).strip()
                if not joined2:
                    i += 1
                    continue
                if extract_answer_choice(joined2):
                    break
                if ANS_HEADER_RE.match(joined2):
                    break
                if chapter_header_re.match(joined2):
                    break
                if ANSWER_HEADER_RE.match(joined2):
                    break
                cur['explanation'] += '\n' + joined2
                i += 1
            continue

        # 综合应用题答案头
        m = ANS_HEADER_RE.match(joined)
        if m:
            save_cur()
            cur = {'id': m.group(1).zfill(2), 'choice': None,
                   'explanation': '【解答】', '_section': 'app'}
            i += 1
            while i < len(answer_lines):
                ln2 = answer_lines[i]
                joined2 = ' '.join(ln2['texts']).strip()
                if not joined2:
                    i += 1
                    continue
                if extract_answer_choice(joined2) or ANS_HEADER_RE.match(joined2):
                    break
                if chapter_header_re.match(joined2):
                    break
                if ANSWER_HEADER_RE.match(joined2):
                    break
                cur['explanation'] += '\n' + joined2
                i += 1
            continue

        # 兼容没有 "【解答】" 的应用题答案，如 "01. 答案：..."
        if section == 'app' and cur is None and APP_ANS_START_RE.match(joined) and not extract_answer_choice(joined):
            m = APP_ANS_START_RE.match(joined)
            cur = {'id': m.group(1).zfill(2), 'choice': None,
                   'explanation': m.group(2).strip(), '_section': 'app'}
            i += 1
            while i < len(answer_lines):
                ln2 = answer_lines[i]
                joined2 = ' '.join(ln2['texts']).strip()
                if not joined2:
                    i += 1
                    continue
                if extract_answer_choice(joined2) or ANS_HEADER_RE.match(joined2) or APP_ANS_START_RE.match(joined2):
                    break
                if chapter_header_re.match(joined2):
                    break
                if ANSWER_HEADER_RE.match(joined2):
                    break
                cur['explanation'] += '\n' + joined2
                i += 1
            continue

        if cur is not None and cur['explanation'] is not None:
            cur['explanation'] += '\n' + joined
        i += 1

    save_cur()
    return {'choice': choice_answers, 'app': app_answers}


def main():
    # CLI overrides
    global OCR_DIR, QA_JSON, TOC_JSON, OUTPUT_JSON, COURSE_TITLE, TOTAL_PAGES
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--ocr-dir' and i + 1 < len(args):
            OCR_DIR = Path(args[i+1]); i += 2
        elif a == '--qa-json' and i + 1 < len(args):
            QA_JSON = args[i+1]; i += 2
        elif a == '--toc-json' and i + 1 < len(args):
            TOC_JSON = args[i+1]; i += 2
        elif a == '--output' and i + 1 < len(args):
            OUTPUT_JSON = args[i+1]; i += 2
        elif a == '--title' and i + 1 < len(args):
            COURSE_TITLE = args[i+1]; i += 2
        elif a == '--total-pages' and i + 1 < len(args):
            TOTAL_PAGES = int(args[i+1]); i += 2
        else:
            i += 1
    qa_pairs_data = json.load(open(QA_JSON, encoding='utf-8'))
    qa_pairs = qa_pairs_data['qa_pairs'] if isinstance(qa_pairs_data, dict) else qa_pairs_data

    all_pages_text = {}
    for f in OCR_DIR.glob('*.json'):
        page_num = int(f.stem.split('_')[-1])
        all_pages_text[page_num] = json.load(open(f, encoding='utf-8'))

    final_chapters = []
    summary = []
    toc = json.load(open(TOC_JSON, encoding='utf-8'))

    for idx, qa in enumerate(qa_pairs):
        topic = qa['topic_title']
        m = re.match(r'^(\d+\.\d+(?:\.\d+)?)', topic)
        chap_num = m.group(1) if m else topic
        q_start = qa['q_start']
        l1_name = None
        l2_name = None
        for entry in toc:
            if entry[0] == 1 and entry[2] <= q_start:
                l1_name = entry[1]
            if entry[0] == 2 and entry[2] <= q_start:
                l2_name = entry[1]

        # 题目区包含答案起始页中「答案与解析」标题之前的内容，防止题干/选项跨到该页时被截断
        q_pages = list(range(qa['q_start'], max(qa['a_start'] + 1, qa['q_start']+1)))
        if idx + 1 < len(qa_pairs):
            next_q_start = qa_pairs[idx+1]['q_start']
            a_pages = list(range(qa['a_start'], max(next_q_start, qa['a_start']+1)))
        else:
            a_pages = list(range(qa['a_start'], TOTAL_PAGES + 1))

        page_w = 600
        for p in q_pages:
            if p in all_pages_text:
                for b in all_pages_text[p].get('blocks', []):
                    page_w = max(page_w, b.get('x1', 0))

        # 跨页连续解析题目，避免跨页选择题被拆分为综合应用题
        question_pages_data = [all_pages_text[p] for p in q_pages if p in all_pages_text]
        questions = parse_questions_span(question_pages_data, page_w)

        # 应用题在答案区通常按独立小节重新编号（01, 02...），
        # 而题干区可能用连续编号。这里按出现顺序重新编号应用题，
        # 使其与答案区的 "01.【解答】" 等对齐。
        app_counter = 1
        for q in questions:
            if q.get('type') != '选择题':
                q['id'] = str(app_counter).zfill(2)
                app_counter += 1

        all_answers_by_section = {'choice': {}, 'app': {}}
        for p in a_pages:
            if p not in all_pages_text:
                continue
            ans = parse_answer_page(all_pages_text[p])
            for sec in ('choice', 'app'):
                all_answers_by_section[sec].update(ans.get(sec, {}))

        # 合并到questions - 转换为 schema 格式
        for q in questions:
            qid = q['id']
            qtype = q.get('type', '选择题')
            sec = 'choice' if qtype == '选择题' else 'app'
            ans = all_answers_by_section.get(sec, {}).get(qid)
            # content 转 LaTeX-friendly 的简单形式
            content_text = q['content'].strip()
            # options 保留 {A: ..., B: ...}
            options_dict = q.get('options', {})
            # sub_questions: 暂为 None
            sub_qs = None
            answer_dict = None
            if ans:
                explanation = (ans.get('explanation') or '').strip()
                # 去除解释中开头的 "【解答】"
                if explanation.startswith('【解答】'):
                    explanation = explanation[len('【解答】'):].strip()
                answer_dict = {
                    'choice': ans.get('choice'),
                    'explanation': explanation,
                }
            q_out = {
                'id': qid,
                'type': qtype,
                'content': content_text,
                'options': options_dict if options_dict else None,
                'sub_questions': sub_qs,
                'page': qa['q_start'],
                'has_image': False,
                'image_ref': None,
                'topic_title': topic,
                'answer': answer_dict,
                'q_pages': q_pages,
                'a_pages': a_pages,
            }
            q.clear()
            q.update(q_out)

        if not questions:
            print(f"[!] {topic}: 0 questions (q_pages={q_pages}, a_pages={a_pages})")

        chapter = {
            'topic_title': topic,
            'chap_num': chap_num,
            'l1_name': l1_name,
            'l2_name': l2_name,
            'question_count': len(questions),
            'questions': questions,
            'q_pages': q_pages,
            'a_pages': a_pages,
        }
        final_chapters.append(chapter)
        summary.append({
            'topic': topic,
            'q_count': len(questions),
            'a_choice': len(all_answers_by_section.get('choice', {})),
            'a_app': len(all_answers_by_section.get('app', {})),
            'q_pages': q_pages,
            'a_pages': a_pages,
        })
        print("[%d/%d] %s: %d题, 选择答案%d条, 应用答案%d条" % (
            idx+1, len(qa_pairs), topic, len(questions),
            len(all_answers_by_section.get('choice', {})),
            len(all_answers_by_section.get('app', {}))))

    total_q = sum(c['question_count'] for c in final_chapters)
    out = {
        'title': COURSE_TITLE,
        'total_pages': TOTAL_PAGES,
        'total_questions': total_q,
        'chapters': final_chapters,
    }
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n总题数: {total_q}")
    with open('scripts_output/extraction_summary.json', 'w', encoding='utf-8') as f:
        json.dump({'chapters': summary, 'total': total_q}, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
