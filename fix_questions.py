#!/usr/bin/env python3
"""
对 questions_*.json 应用安全的自动修复：
  1. 从解析文本中提取缺失的选择题答案 choice
  2. 拆分题干中的子问题标记 （1）...（2）... 为 sub_questions
  3. 对题干含图标记的题目设置 has_image=true（关联到所在页原图）
  4. 清理空 explanation 占位符
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

IMAGE_MARKERS = ['图', '如图', '见下图', '如下图所示', '如图所示']


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


def detect_image_ref(q, pdf_images_dir):
    """如果题干含图标记且所在页有截图，返回 image_ref。
    cropped 路径相对于 math-bank/index.html（即 ../pdf_images_xxx/page_NNN.png）。"""
    content = q.get('content') or ''
    if not any(m in content for m in IMAGE_MARKERS):
        return None
    page = q.get('page')
    if not page:
        return None
    page_file = f'page_{page:03d}.png'
    # 尝试多个可能的图片目录命名
    candidates = [
        pdf_images_dir / page_file,
        Path('pdf_images') / page_file,
    ]
    for p in candidates:
        if p.exists():
            # 转换为前端可访问的相对路径
            rel = p.as_posix()
            if not rel.startswith('../'):
                rel = '../' + rel
            return {'page': page, 'note': '题干含图，已关联到原题页', 'cropped': rel}
    return None


def fix_file(path, pdf_images_dir=None):
    path = Path(path)
    data = json.load(open(path, encoding='utf-8'))
    fixes = {
        'choice_filled': 0,
        'sub_questions_split': 0,
        'image_ref_added': 0,
        'empty_explanation_cleaned': 0,
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

            # 2. 拆分子问题
            content = q.get('content') or ''
            if not q.get('sub_questions'):
                main, subs = split_sub_questions(content)
                if subs:
                    q['content'] = main
                    q['sub_questions'] = subs
                    fixes['sub_questions_split'] += 1

            # 3. 图片关联
            ref = q.get('image_ref')
            if not q.get('has_image') or not ref or not ref.get('cropped'):
                new_ref = detect_image_ref(q, pdf_images_dir or Path('pdf_images'))
                if new_ref:
                    q['has_image'] = True
                    q['image_ref'] = new_ref
                    fixes['image_ref_added'] += 1

            # 4. 清理空 explanation
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
    files = sys.argv[1:] or ['questions.json', 'questions_coa.json', 'questions_net.json', 'questions_os.json']
    total = {}
    for fn in files:
        p = Path(fn)
        if not p.exists():
            print(f'[skip] {fn} not found')
            continue
        # 根据文件名推断图片目录
        stem = p.stem
        if stem == 'questions':
            img_dir = Path('pdf_images')
        else:
            img_dir = Path(f'pdf_images_{stem.replace("questions_", "")}')
        fixes = fix_file(p, img_dir)
        for k, v in fixes.items():
            total[k] = total.get(k, 0) + v
    print(f'总计修复: {total}')


if __name__ == '__main__':
    main()
