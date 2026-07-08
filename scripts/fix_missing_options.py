#!/usr/bin/env python3
"""自动修复缺失选项的选择题。

策略：
1. 读取 tmp/missing_options_after_split.json 中 questions_all.json 的缺失清单。
2. 在 output/questions_{key}.json 中定位对应题目。
3. 按题目 bbox + 扩展区域裁剪原题图片，对裁剪区域重新跑 RapidOCR。
4. 从 OCR 结果中尝试提取缺失的 A/B/C/D 选项文本。
5. 将高置信度修复结果写回源文件，并输出剩余未修复清单。
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
MISSING_JSON = ROOT / 'tmp' / 'missing_options_after_split.json'
REPORT_DIR = ROOT / 'tmp' / 'missing_option_crops'

# 课程元数据（与 config.py 保持一致，避免循环导入）
COURSES = {
    '数据结构': {'key': 'ds', 'images': ROOT / 'assets/pdf_images/ds', 'out': ROOT / 'output' / 'questions.json'},
    '计算机组成原理': {'key': 'coa', 'images': ROOT / 'assets/pdf_images/coa', 'out': ROOT / 'output' / 'questions_coa.json'},
    '计算机网络': {'key': 'net', 'images': ROOT / 'assets/pdf_images/net', 'out': ROOT / 'output' / 'questions_net.json'},
    '操作系统': {'key': 'os', 'images': ROOT / 'assets/pdf_images/os', 'out': ROOT / 'output' / 'questions_os.json'},
}

OPTION_LABEL_RE = re.compile(r'([A-D])[\.．、]\s*(.+)')


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def find_question(data, qid, page, section_hint):
    """在 questions_*.json 中定位题目。匹配 id + page，若多个则按 section_hint 辅助。"""
    candidates = []
    for ch in data.get('chapters', []):
        topic = ch.get('topic_title', '') or ch.get('name', '')
        for q in ch.get('questions', []):
            if q.get('id') == qid and q.get('page') == page:
                candidates.append((ch, q, topic))
    if not candidates:
        return None, None
    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1]
    # 多个候选时按 section_hint 模糊匹配
    for ch, q, topic in candidates:
        if section_hint and section_hint in topic:
            return ch, q
    return candidates[0][0], candidates[0][1]


def crop_question_area(img_path, bbox, padding=20):
    """按 bbox 扩展 padding 后裁剪。"""
    try:
        img = Image.open(img_path)
    except Exception as e:
        print(f'  [warn] 无法打开图片 {img_path}: {e}')
        return None
    w, h = img.size
    x0 = max(0, int(bbox[0]) - padding)
    y0 = max(0, int(bbox[1]) - padding)
    x1 = min(w, int(bbox[2]) + padding)
    y1 = min(h, int(bbox[3]) + padding)
    if x1 <= x0 or y1 <= y0:
        return None
    return img.crop((x0, y0, x1, y1))


def recognize_crop(crop_img, ocr):
    """对裁剪图跑 OCR，返回识别到的文本行列表。"""
    result, _ = ocr(crop_img)
    if not result:
        return []
    # rapidocr 返回格式：[[[box], (text, score)], ...]
    lines = []
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
            lines.append(text)
        elif isinstance(item, str):
            lines.append(item)
    return lines


def extract_missing_options(lines, missing_letters):
    """从 OCR 文本行中提取缺失选项。
    返回 {letter: text} 或 None（未识别到）。"""
    found = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = OPTION_LABEL_RE.match(line)
        if m:
            letter = m.group(1)
            text = m.group(2).strip()
            if letter in missing_letters and text:
                found[letter] = text
    return found if found else None


def main():
    if not MISSING_JSON.exists():
        print(f'[error] 找不到缺失清单 {MISSING_JSON}')
        sys.exit(1)
    missing = load_json(MISSING_JSON)
    items = missing.get('questions_all.json', [])
    print(f'[info] 共 {len(items)} 道选项不全题目待修复')

    PROGRESS_PATH = ROOT / 'tmp' / 'missing_options_fix_progress.json'
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    progress = load_json(PROGRESS_PATH) if PROGRESS_PATH.exists() else {}
    done_keys = set(progress.get('done', []))
    fixed = progress.get('fixed', [])
    unresolved = progress.get('unresolved', [])
    skipped_no_bbox = progress.get('skipped_no_bbox', [])

    ocr = RapidOCR()
    # 按课程缓存数据
    course_data = {name: load_json(meta['out']) for name, meta in COURSES.items()}

    def save_course(name):
        save_json(COURSES[name]['out'], course_data[name])
        print(f'  [write-back] {COURSES[name]["out"]}')

    def save_progress():
        save_json(PROGRESS_PATH, {
            'done': sorted(list(done_keys)),
            'fixed': fixed,
            'unresolved': unresolved,
            'skipped_no_bbox': skipped_no_bbox,
        })

    for idx, item in enumerate(items):
        qid, page, present_letters, section = item
        key = f'{qid}|{page}|{"".join(present_letters)}|{section}'
        if key in done_keys:
            continue
        done_keys.add(key)
        missing_letters = [l for l in 'ABCD' if l not in present_letters]

        # 找到对应课程和题目
        ch = None
        q = None
        course_name = None
        for name, data in course_data.items():
            ch, q = find_question(data, qid, page, section)
            if q:
                course_name = name
                break
        if not q:
            print(f'  [skip] 找不到题目 {qid} page {page}')
            unresolved.append({'reason': 'not_found', 'item': item})
            save_progress()
            continue

        bbox = q.get('bbox')
        if not bbox:
            skipped_no_bbox.append(item)
            save_progress()
            continue

        img_path = COURSES[course_name]['images'] / f'page_{page:03d}.png'
        if not img_path.exists():
            print(f'  [skip] 找不到图片 {img_path}')
            unresolved.append({'reason': 'no_image', 'item': item})
            save_progress()
            continue

        crop = crop_question_area(img_path, bbox, padding=20)
        if crop is None:
            unresolved.append({'reason': 'crop_failed', 'item': item})
            save_progress()
            continue

        lines = recognize_crop(crop, ocr)
        found = extract_missing_options(lines, missing_letters)

        if found:
            options = q.get('options') or {}
            options.update(found)
            q['options'] = options
            fixed.append({
                'course': course_name,
                'qid': qid,
                'page': page,
                'found': found,
            })
            save_course(course_name)
            print(f'  [fixed] {course_name} {qid} page {page}: {found}')
        else:
            # 只有 unresolved 才保存 crop 图供人工核对
            crop_name = f'{COURSES[course_name]["key"]}_page{page:03d}_{qid}.png'
            crop_path = REPORT_DIR / crop_name
            crop.save(crop_path, 'PNG')
            unresolved.append({
                'reason': 'ocr_no_option',
                'item': item,
                'crop': str(crop_path.relative_to(ROOT)),
                'ocr_lines': lines,
            })
            print(f'  [unresolved] {course_name} {qid} page {page}')
        save_progress()

    # 最终输出报告
    report = {
        'fixed_count': len(fixed),
        'unresolved_count': len(unresolved),
        'skipped_no_bbox_count': len(skipped_no_bbox),
        'fixed': fixed,
        'unresolved': unresolved,
        'skipped_no_bbox': skipped_no_bbox,
    }
    report_path = ROOT / 'tmp' / 'missing_options_fix_report.json'
    save_json(report_path, report)
    print(f'\n[summary] fixed={len(fixed)}, unresolved={len(unresolved)}, no_bbox={len(skipped_no_bbox)}')
    print(f'[report] {report_path}')


if __name__ == '__main__':
    main()
