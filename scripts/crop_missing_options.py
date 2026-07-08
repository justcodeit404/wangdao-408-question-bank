#!/usr/bin/env python3
"""为当前所有缺失选项的题目生成 crop 图，便于人工核对。"""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'tmp' / 'missing_option_crops_new'
OUT_DIR.mkdir(parents=True, exist_ok=True)

COURSES = {
    'ds': ('数据结构', ROOT / 'output' / 'questions.json', ROOT / 'assets/pdf_images/ds'),
    'coa': ('计算机组成原理', ROOT / 'output' / 'questions_coa.json', ROOT / 'assets/pdf_images/coa'),
    'net': ('计算机网络', ROOT / 'output' / 'questions_net.json', ROOT / 'assets/pdf_images/net'),
    'os': ('操作系统', ROOT / 'output' / 'questions_os.json', ROOT / 'assets/pdf_images/os'),
}

for key, (name, json_path, img_dir) in COURSES.items():
    data = json.loads(json_path.read_text(encoding='utf-8'))
    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            if q.get('type') != '选择题':
                continue
            opts = q.get('options', {})
            missing = [l for l in 'ABCD' if l not in opts]
            if not missing:
                continue
            page = q.get('page')
            bbox = q.get('bbox')
            if not page or not bbox:
                continue
            img_path = img_dir / f'page_{page:03d}.png'
            if not img_path.exists():
                continue
            try:
                img = Image.open(img_path)
            except Exception:
                continue
            w, h = img.size
            x0 = max(0, int(bbox[0]) - 20)
            y0 = max(0, int(bbox[1]) - 20)
            x1 = min(w, int(bbox[2]) + 20)
            y1 = min(h, int(bbox[3]) + 20)
            if x1 <= x0 or y1 <= y0:
                continue
            crop = img.crop((x0, y0, x1, y1))
            out_name = f'{key}_page{page:03d}_{q["id"]}.png'
            crop.save(OUT_DIR / out_name, 'PNG')
            print(f'{name} {q["id"]} page {page} missing {"".join(missing)} -> {out_name}')
