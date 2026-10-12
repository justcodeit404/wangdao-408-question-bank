#!/usr/bin/env python3
"""四门 408 课程的统一配置。

所有构建脚本都从这里读取课程元数据。PROJECT_ROOT 以本文件所在目录的父目录
（即项目根目录）为基准，因此无论脚本从哪个目录被调用，路径都稳定。
"""
import sys
from dataclasses import dataclass
from pathlib import Path

# 保证 stdout 输出 UTF-8，避免 Windows 终端乱码
sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parents[1]  # bank-408/ -> apps/ -> 考研根


def _path(rel: str) -> Path:
    return PROJECT_ROOT / rel


def _repo_path(rel: str) -> Path:
    return REPO_ROOT / rel


@dataclass(frozen=True)
class Course:
    key: str          # 内部标识：ds / coa / net / os
    name: str         # 完整课程名
    short: str        # 前端展示短名
    pdf: Path         # PDF 文件路径
    ocr_dir: Path     # OCR 输出目录
    qa_json: Path     # QA pairs 文件
    toc_json: Path    # 目录 JSON
    total_pages: int  # PDF 总页数
    out_json: Path    # 最终 questions_{key}.json
    pdf_images_dir: Path


COURSES = [
    Course(
        key='ds',
        name='数据结构',
        short='数据结构',
        pdf=_repo_path('资料/408/27王道《数据结构》高清带书签.pdf'),
        ocr_dir=_path('data/ocr/ds'),
        qa_json=_path('data/qa/qa_pairs.json'),  # 历史文件名；其余三科为 {key}_qa_pairs.json
        toc_json=_path('data/toc/toc.json'),  # 历史文件名；其余三科为 toc_{key}.json
        total_pages=397,
        out_json=_path('output/questions.json'),
        pdf_images_dir=_path('assets/pdf_images/ds'),
    ),
    Course(
        key='coa',
        name='计算机组成原理',
        short='组成原理',
        pdf=_repo_path('资料/408/27王道《计算机组成原理》高清带书签.pdf'),
        ocr_dir=_path('data/ocr/coa'),
        qa_json=_path('data/qa/coa_qa_pairs.json'),
        toc_json=_path('data/toc/toc_coa.json'),
        total_pages=333,
        out_json=_path('output/questions_coa.json'),
        pdf_images_dir=_path('assets/pdf_images/coa'),
    ),
    Course(
        key='os',
        name='操作系统',
        short='操作系统',
        pdf=_repo_path('资料/408/27王道《操作系统》高清带书签.pdf'),
        ocr_dir=_path('data/ocr/os'),
        qa_json=_path('data/qa/os_qa_pairs.json'),
        toc_json=_path('data/toc/toc_os.json'),
        total_pages=365,
        out_json=_path('output/questions_os.json'),
        pdf_images_dir=_path('assets/pdf_images/os'),
    ),
    Course(
        key='net',
        name='计算机网络',
        short='计算机网络',
        pdf=_repo_path('资料/408/27王道《计算机网络》高清带书签.pdf'),
        ocr_dir=_path('data/ocr/net'),
        qa_json=_path('data/qa/net_qa_pairs.json'),
        toc_json=_path('data/toc/toc_net.json'),
        total_pages=309,
        out_json=_path('output/questions_net.json'),
        pdf_images_dir=_path('assets/pdf_images/net'),
    ),
]

# 兼容旧代码：按文件名 -> 课程信息的映射
COURSE_BY_OUT_JSON = {c.out_json.name: c for c in COURSES}
COURSE_BY_KEY = {c.key: c for c in COURSES}


def image_dir_for(out_json: str | Path) -> Path:
    """根据 questions_*.json 文件名推断对应的 PDF 切页图目录。"""
    name = Path(out_json).name
    course = COURSE_BY_OUT_JSON.get(name)
    if course:
        return course.pdf_images_dir
    # 兜底：questions.json -> assets/pdf_images/ds，questions_coa.json -> assets/pdf_images/coa
    stem = Path(name).stem
    key = 'ds' if stem == 'questions' else stem.replace('questions_', '')
    return _path(f'assets/pdf_images/{key}')


# 常用输出路径
OUTPUT_DIR = _path('output')
REPORTS_DIR = _path('output/reports')
MATH_BANK_DIR = _path('math-bank')
