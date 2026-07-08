#!/usr/bin/env python3
"""对 questions_*.json 应用安全的自动修复：
  1. 从解析文本中提取缺失的选择题答案 choice
  2. 拆分题干中的子问题标记 （1）...（2）... 为 sub_questions
  3. 对题干含图标记的题目设置 has_image=true，并按题目 bbox 裁剪出精准截图
  4. 清理空 explanation 占位符
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image

from config import image_dir_for, PROJECT_ROOT, MATH_BANK_DIR, COURSE_BY_OUT_JSON

sys.stdout.reconfigure(encoding='utf-8')

# 题目区域截图的四周留白（像素）
# 原 60 过大会把相邻题目也裁进来；10 足够保留插图边缘，同时最大限度避免混入邻题
CROP_PADDING = 10

# 题干中真正指向附图/插图的短语；避免把“图论”“并查集涉及图”等讨论主题的"图"字误标
IMAGE_MARKERS = [
    '如图', '见下图', '如下图所示', '如图所示', '图中所示',
    '右图', '左图', '下图', '上图', '给出下图', '给出上图',
]

# 不含真实附图的“图”字场景，用于过滤误报
IMAGE_FALSE_POSITIVES = [
    '图的基本概念', '图论', '并查集涉及图', '涉及图', '图的相关', '图的存储',
    '图的遍历', '图的拓扑', '图的最短', '图的最小生成', '图的应用',
    '有向图', '无向图', '连通图', '强连通图', '生成树', '森林',
]


def has_real_image_ref(content):
    """判断题干是否真正指向附图（而非章节术语中的“图”字）。"""
    if not content:
        return False
    # 先排除明确不含图的课程术语
    for fp in IMAGE_FALSE_POSITIVES:
        if fp in content:
            return False
    return any(m in content for m in IMAGE_MARKERS)


# 页眉/页脚噪音：每页顶部/底部可能出现书名，前面可能带页码
# 如 "2027年数据结构考研复习指导" 或 "8 2027年数据结构考研复习指导"
PAGE_NOISE_RE = re.compile(r'\n\s*(?:\d+\s+)?\d{4}年.{0,20}考研复习指导\s*$', re.MULTILINE)
PAGE_NOISE_START_RE = re.compile(r'^\s*(?:\d+\s+)?\d{4}年.{0,20}考研复习指导\s*\n')

# 章节页眉/页脚：如 "第2章线性表 19"、"第 4章 指令系统 153"
CHAPTER_PAGE_NOISE_RE = re.compile(
    r'^\s*第\s*\d+\s*章\s*[^\n]{1,30}?\s+\d+\s*$',
    re.MULTILINE,
)


def clean_content(content):
    """清理题干中的页眉/页脚噪音，如 '2027年数据结构考研复习指导'、'第2章线性表 19'。"""
    if not content:
        return content
    # 去掉末尾单独一行的噪音
    content = PAGE_NOISE_RE.sub('', content)
    # 去掉开头单独一行的噪音（理论上较少）
    content = PAGE_NOISE_START_RE.sub('', content)
    # 去掉章节页眉/页脚行
    content = CHAPTER_PAGE_NOISE_RE.sub('', content)
    return content.strip()


# 题干中常见的插图标注 / OCR 误识别的图注碎片
# xau/π 是 OCR 将图注/箭头误识别成的无意义字符；<- 在 C/C++ 题干中通常也是图注箭头
DIAGRAM_ARTIFACT_PATTERNS = [
    # 2012 统考真题“loading 和 being 共同后缀”一题的图注碎片
    r'^\s*strl[、,，]?\s*$',
    r'^\s*str2\s*$',
    r'^\s*[→\-~]+\s*n\s*[→\-~]+\s*g\s*$',
    # 无意义的 OCR 乱码
    r'\bxau\b',
    r'π',
]
DIAGRAM_ARTIFACT_RE = re.compile('|'.join(f'({p})' for p in DIAGRAM_ARTIFACT_PATTERNS), re.MULTILINE)

# 从图注碎片行中抢救被混入的选项，如 "N==x-==<- ' B. L->prior==NULL&&L->next==NULL"
OPTION_IN_GARBAGE_RE = re.compile(r'([A-Da-d])[\.．、]\s*(.+?)(?=\s+[A-Da-d][\.．、]\s*|$)', re.DOTALL)


def is_diagram_artifact_line(line):
    """判断一行是否为图注/OCR 碎片行。

    注意：像 'x<-16' 这种数学比较式虽然包含 '<-' 子串，但不是图注碎片，
    需要排除。
    """
    if not line.strip():
        return False
    # 明确的 OCR 乱码
    if re.search(r'\bxau\b|π', line):
        return True
    # 图注选项标签行，如 "(d) ad<-d=xau..."
    if re.match(r'^\s*[（(]\s*d\s*[）)]', line):
        return True
    # 包含 <- 箭头时，需排除数学比较式（如 x<-16, a<-b 且整体为合法表达式）
    if '<-' in line:
        # 行首为 ! : = 等图注符号，肯定是碎片
        if re.match(r'^\s*[!:=]', line):
            return True
        # 若只有一个 <- 且前后是 ASCII 标识符/数字（比较式），保留
        arrows = re.findall(r'<-(?!=)', line)
        if len(arrows) == 1 and '->' not in line:
            m = re.search(r'([A-Za-z0-9_]+)<-(-?[A-Za-z0-9_]+)', line)
            if m:
                return False
        # 多个 <- 或混有 -> 等，视为图注箭头碎片
        return True
    return False


# 罗马数字，避免被误当作图注标签块清理
_ROMAN_NUMERALS = {'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'}
_LABEL_LINE_RE = re.compile(r'^[A-Za-z0-9\s]+$')


def _is_label_line(line):
    """判断一行是否为图注标签行：仅含字母/数字/空格，长度<=4，且非罗马数字。"""
    s = line.strip()
    if not s or len(s) > 4 or s in _ROMAN_NUMERALS:
        return False
    return bool(_LABEL_LINE_RE.match(s))


def _strip_trailing_label_block(lines):
    """移除题干末尾的连续图注标签块，如：
       ALU\nCO\nB\nM\nMAR\nPC  或单独一行的 P。
    返回 (清理后的行列表, 被移除的行数)。"""
    if not lines:
        return lines, 0
    # 从末尾找连续标签行
    end = len(lines)
    while end > 0 and _is_label_line(lines[end - 1]):
        end -= 1
    label_block = lines[end:]
    if not label_block:
        return lines, 0
    # 只有一行时，仅当它是单个字符才清理（避免误删合法短缩写）
    if len(label_block) == 1 and len(label_block[0].strip()) > 1:
        return lines, 0
    # 多行标签块中若包含过长行（3-4字符），确认这是标签列表：
    # 块中至少有一行长度<=2，或者块长度>=2且全部<=4（已满足）
    if len(label_block) >= 2 and not any(len(l.strip()) <= 2 for l in label_block):
        return lines, 0
    return lines[:end], len(label_block)


def fix_common_ocr_errors(text):
    """修正 OCR 常见错误，如图论题中 V5 被误识别为 Vs、罗马数字被误识别。"""
    if not text:
        return text
    # V5 被误识别为 Vs；V5s 是 Vs 后再多识别一个 s
    text = re.sub(r'(?<![A-Za-z0-9_])V5s(?![A-Za-z0-9_])', 'V5', text)
    text = re.sub(r'(?<![A-Za-z0-9_])Vs(?![A-Za-z0-9_])', 'V5', text)
    # 小写 v5 被误识别为 vs（出现在选项序列中）
    text = re.sub(r'(?<![A-Za-z0-9_])vs(?![A-Za-z0-9_])', 'v5', text)

    # 罗马数字 OCR 修正：OCR 常把 II/III 识别成全角罗马数字与字母 I 的混合
    # 如 ⅡI -> II、IⅢI -> III、ⅢI -> III、ⅠI -> II
    text = text.replace('ⅡI', 'II').replace('IⅢI', 'III').replace('ⅢI', 'III')
    text = text.replace('ⅠI', 'II').replace('ⅠⅠ', 'II').replace('ⅠⅠⅠ', 'III')
    # 剩余全角罗马数字统一转成 ASCII
    text = (text
            .replace('Ⅰ', 'I').replace('Ⅱ', 'II').replace('Ⅲ', 'III')
            .replace('Ⅳ', 'IV').replace('Ⅴ', 'V').replace('Ⅵ', 'VI')
            .replace('Ⅶ', 'VII').replace('Ⅷ', 'VIII').replace('Ⅸ', 'IX')
            .replace('Ⅹ', 'X'))

    # 时间复杂度中 O 被误识别为 0，如 0(n) -> O(n)
    text = re.sub(r'(?<![A-Za-z0-9_])0\(([^)]+)\)', r'O(\1)', text)
    return text


def clean_option_trailing_punct(text):
    """清理选项末尾的异常标点，如 OCR 把题干右括号误识别进选项：'链式存储方式》'。"""
    if not text:
        return text
    # 删除末尾单独的 》，除非文本中包含 《
    if text.endswith('》') and '《' not in text:
        text = text[:-1]
    # 删除末尾单独的 ），除非文本中包含 （
    if text.endswith('）') and '（' not in text:
        text = text[:-1]
    return text.rstrip()


# 选项标签，支持 A./A．/A、 等
OPTION_LABEL_RE = re.compile(r'([B-D])[\.．、]\s*')


def split_merged_options(options):
    """拆分被合并到前一个选项里的选项，如 A: '抽象数据类型B．逻辑结构' -> A+B 分离。
    返回 (是否发生拆分, 新 options)。"""
    if not options:
        return False, options
    changed = False
    new_opts = dict(options)
    for letter in 'ABC':
        if letter not in new_opts:
            continue
        text = new_opts[letter]
        nxt = chr(ord(letter) + 1)
        # 在当前选项文本中查找下一个选项标签（如 B. / B．）
        m = OPTION_LABEL_RE.search(text)
        if not m:
            continue
        split_pos = m.start()
        prefix = text[:split_pos].rstrip()
        suffix = text[m.end():].strip()
        found_label = m.group(1)
        # 仅当发现的标签正好是当前选项的下一个字母时才拆分
        if found_label == nxt and prefix and suffix:
            new_opts[letter] = prefix
            new_opts[found_label] = suffix
            changed = True
    return changed, new_opts


def clean_diagram_artifacts(content, options=None):
    """清理题干中混入的图注/箭头碎片，如 'strl、'、'→n→g'、'str2'、'xau...'。
    同时从碎片行中抢救 A./B./C./D. 选项文本，补充到 options 字典中。"""
    if not content:
        return content
    options = options or {}
    lines = content.split('\n')

    # 1. 清理题干末尾的图注标签块
    lines, _ = _strip_trailing_label_block(lines)

    # 2. 清理行内/行间 OCR 箭头碎片
    cleaned_lines = []
    for line in lines:
        if is_diagram_artifact_line(line):
            # 尝试抢救该行中的选项
            for m in OPTION_IN_GARBAGE_RE.finditer(line):
                letter = m.group(1).upper()
                text = m.group(2).strip().replace('\n', ' ')
                if letter not in options and text:
                    options[letter] = text
            continue
        cleaned_lines.append(line)
    cleaned = '\n'.join(cleaned_lines)
    cleaned = DIAGRAM_ARTIFACT_RE.sub('', cleaned)
    # OCR 常把 str1 误识别为 strl；在题干中纠正好让正文更自然
    cleaned = re.sub(r'(?<![A-Za-z0-9_])strl(?![A-Za-z0-9_])', 'str1', cleaned)
    cleaned = re.sub(r'\n\s*\n+', '\n\n', cleaned)
    return cleaned.strip()


def extract_choice_from_explanation(expl):
    """从解析文本中提取答案字母，如 '答案：C'、'【答案】C'、'答案 C'、'答案：B、D'。"""
    if not expl:
        return None
    patterns = [
        r'[\【\[]?答案[\】\]]?[:：\s]+([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)',
        r'答案[:：\s]*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)',
        r'[\【\[]答案[\】\]][\s:：]*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)',
    ]
    for p in patterns:
        m = re.search(p, expl)
        if m:
            return ''.join(re.findall(r'[A-Ga-g]', m.group(1))).upper()
    return None


def split_sub_questions(content):
    """识别题干中的 （1）...（2）... 并拆分。返回 (主题干, [子问1, 子问2, ...])。
    如果无法拆分，返回 (content, None)。"""
    if not content:
        return content, None
    # 支持中文括号 （1） 和半角括号 (1)
    pattern = r'[\(（]([1-9]\d*)[\)）]'
    markers = list(re.finditer(pattern, content))
    if len(markers) < 2:
        return content, None

    main = content[:markers[0].start()].strip()
    subs = []
    for i, m in enumerate(markers):
        start = m.start()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(content)
        sub = content[start:end].strip()
        if sub:
            subs.append(sub)
    return main, subs if subs else None


# 题干中暗示图位于右侧/下方的关键词
RIGHT_IMAGE_MARKERS = ['右图', '右下图', '右上图']
LEFT_IMAGE_MARKERS = ['左图', '左下图', '左上图']
BELOW_IMAGE_MARKERS = ['下图', '如下图所示', '见下图', '给出下图']
ABOVE_IMAGE_MARKERS = ['上图', '见上图', '给出上图']


def crop_question_image(page_path, page, bbox, course_key, qid, content=''):
    """按题目文本 bbox 裁剪对应页图片，保存到 math-bank/crops/<course_key>/ 下。
    若题干含"右图/左图"等提示，会相应扩展裁剪范围以包含插图。
    返回输出路径；若失败返回 None。"""
    try:
        img = Image.open(page_path)
    except Exception as e:
        print(f'[crop error] open {page_path}: {e}')
        return None
    w, h = img.size
    x0, y0, x1, y1 = bbox
    x0 = max(0, int(x0) - CROP_PADDING)
    y0 = max(0, int(y0) - CROP_PADDING)
    x1 = min(w, int(x1) + CROP_PADDING)
    y1 = min(h, int(y1) + CROP_PADDING)

    # 根据题干中的图位置提示扩展裁剪区域。
    # 实践中"右图"的图常在题干右侧，OCR 给出的 bbox 宽度可能未覆盖插图，
    # 因此把右侧边界扩展到页面右边缘（保留少量边距）。
    if content:
        if any(m in content for m in RIGHT_IMAGE_MARKERS):
            x1 = min(w, max(x1, w - 20))
        if any(m in content for m in LEFT_IMAGE_MARKERS):
            x0 = max(0, min(x0, 20))

    if x1 <= x0 or y1 <= y0:
        return None
    cropped = img.crop((x0, y0, x1, y1))
    out_dir = MATH_BANK_DIR / 'crops' / course_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'page_{page:03d}_{qid}.png'
    cropped.save(out_path, 'PNG')
    return out_path


def detect_image_ref(q, pdf_images_dir, course_key=None):
    """如果题干含图标记且所在页有截图，返回 image_ref。
    优先按题目 bbox 裁剪出精准截图；没有 bbox 时回退到整页原图。"""
    content = q.get('content') or ''
    if not has_real_image_ref(content):
        return None
    page = q.get('page')
    if not page:
        return None
    page_file = f'page_{page:03d}.png'
    candidates = [
        pdf_images_dir / page_file,
        PROJECT_ROOT / 'assets/pdf_images/ds' / page_file,
    ]
    page_path = None
    for p in candidates:
        if p.exists():
            page_path = p
            break
    if not page_path:
        return None

    bbox = q.get('bbox')
    if bbox and course_key:
        crop_path = crop_question_image(page_path, page, bbox, course_key, q.get('id', '00'), content=content)
        if crop_path:
            rel = crop_path.relative_to(MATH_BANK_DIR).as_posix()
            return {'page': page, 'note': '题干含图，已按题目区域裁剪', 'cropped': rel}

    # 回退：关联整页原图
    rel = page_path.relative_to(PROJECT_ROOT).as_posix()
    if not rel.startswith('../'):
        rel = '../' + rel
    return {'page': page, 'note': '题干含图，已关联到原题页', 'cropped': rel}


def fix_file(path, pdf_images_dir=None, course_key=None):
    path = Path(path)
    if course_key is None:
        course = COURSE_BY_OUT_JSON.get(path.name)
        course_key = getattr(course, 'key', None) if course else None
    data = json.load(open(path, encoding='utf-8'))
    fixes = {
        'choice_filled': 0,
        'sub_questions_split': 0,
        'image_ref_added': 0,
        'empty_explanation_cleaned': 0,
        'content_noise_cleaned': 0,
    }

    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            ans = q.get('answer') or {}
            expl = (ans.get('explanation') or '').strip()

            # 1. 提取缺失的选择题答案
            if q.get('type') == '选择题' and not ans.get('choice') and expl:
                choice = extract_choice_from_explanation(expl)
                if choice:
                    ans['choice'] = choice
                    q['answer'] = ans
                    fixes['choice_filled'] += 1

            # 2. 清理题干中的页眉/页脚噪音
            content = q.get('content') or ''
            cleaned = clean_content(content)
            # 3. 清理图注 / OCR 箭头碎片，同时从碎片中抢救选项
            options = q.get('options') or {}
            cleaned2 = clean_diagram_artifacts(cleaned, options)
            if cleaned2 != content or options != q.get('options'):
                q['content'] = cleaned2
                if options:
                    q['options'] = options
                fixes['content_noise_cleaned'] += 1

            # 3.5 全局 OCR 错误修正（Vs→V5 等）
            q['content'] = fix_common_ocr_errors(q.get('content') or '')
            if q.get('options'):
                for k, v in q['options'].items():
                    v = fix_common_ocr_errors(v)
                    q['options'][k] = clean_option_trailing_punct(v)
                # 3.6 拆分被合并的选项（如 A 里包含 B.）
                changed, new_opts = split_merged_options(q['options'])
                if changed:
                    q['options'] = new_opts
                    fixes['content_noise_cleaned'] += 1
            if ans.get('explanation'):
                ans['explanation'] = fix_common_ocr_errors(ans['explanation'])
                q['answer'] = ans

            # 5. 拆分子问题
            if not q.get('sub_questions'):
                main, subs = split_sub_questions(cleaned)
                if subs:
                    q['content'] = main
                    q['sub_questions'] = subs
                    fixes['sub_questions_split'] += 1

            # 6. 图片关联
            ref = q.get('image_ref')
            cropped_missing = ref and ref.get('cropped') and not (MATH_BANK_DIR / ref['cropped']).exists()
            needs_image = not q.get('has_image') or not ref or not ref.get('cropped') or cropped_missing
            if needs_image:
                new_ref = detect_image_ref(q, pdf_images_dir or image_dir_for(path.name), course_key=course_key)
                if new_ref:
                    q['has_image'] = True
                    q['image_ref'] = new_ref
                    fixes['image_ref_added'] += 1

            # 7. 清理空 explanation
            if ans and not ans.get('choice') and not expl:
                if 'answer' in q and q['answer'] is not None and not any(q['answer'].values()):
                    q['answer'] = None
                    fixes['empty_explanation_cleaned'] += 1

    data['total_questions'] = sum(ch['question_count'] for ch in data.get('chapters', []))
    out_path = path
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Fixed {path}: {fixes}')
    return fixes


def main():
    files = sys.argv[1:] or [
        'output/questions.json',
        'output/questions_coa.json',
        'output/questions_net.json',
        'output/questions_os.json',
    ]
    total = {}
    for fn in files:
        p = Path(fn)
        if not p.exists():
            print(f'[skip] {fn} not found')
            continue
        fixes = fix_file(p, image_dir_for(p.name))
        for k, v in fixes.items():
            total[k] = total.get(k, 0) + v
    print(f'总计修复: {total}')


if __name__ == '__main__':
    main()
