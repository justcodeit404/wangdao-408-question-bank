#!/usr/bin/env python3
"""构建流程集成测试：parse_questions -> post_process -> reshape_by_l2 -> fix_questions。

用合成 fixture 跑一遍完整流水线，验证输出结构正确。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def synthetic_course(tmp_path):
    """在临时目录里构造一门迷你课程所需的数据。"""
    ocr_dir = tmp_path / 'ocr'
    ocr_dir.mkdir()

    # 题目页：2 道选择题 + 1 道应用题
    question_page = {
        'page': 10,
        'blocks': [
            {'y0': 50, 'x0': 50, 'x1': 500, 'text': '1.1.1 本节试题精选'},
            {'y0': 100, 'x0': 50, 'x1': 80, 'text': '01.'},
            {'y0': 100, 'x0': 100, 'x1': 500, 'text': '第一题题干'},
            {'y0': 140, 'x0': 50, 'x1': 200, 'text': 'A. 选项A'},
            {'y0': 140, 'x0': 250, 'x1': 400, 'text': 'B. 选项B'},
            {'y0': 180, 'x0': 50, 'x1': 80, 'text': '02.'},
            {'y0': 180, 'x0': 100, 'x1': 500, 'text': '第二题题干'},
            {'y0': 220, 'x0': 50, 'x1': 200, 'text': 'A. 选项1'},
            {'y0': 220, 'x0': 250, 'x1': 400, 'text': 'B. 选项2'},
            {'y0': 260, 'x0': 50, 'x1': 80, 'text': '03.'},
            {'y0': 260, 'x0': 100, 'x1': 500, 'text': '应用题题干'},
            # 页脚噪音：应被过滤，不能混入题干
            {'y0': 300, 'x0': 50, 'x1': 500, 'text': '2027年数据结构考研复习指导'},
        ]
    }

    # 答案页
    answer_page = {
        'page': 11,
        'blocks': [
            {'y0': 50, 'x0': 50, 'x1': 500, 'text': '1.1.1 答案与解析'},
            {'y0': 100, 'x0': 50, 'x1': 500, 'text': '一、单项选择题'},
            {'y0': 140, 'x0': 50, 'x1': 100, 'text': '01. C'},
            {'y0': 170, 'x0': 50, 'x1': 500, 'text': '第一题解析'},
            {'y0': 210, 'x0': 50, 'x1': 100, 'text': '02. A'},
            {'y0': 240, 'x0': 50, 'x1': 500, 'text': '第二题解析'},
            {'y0': 290, 'x0': 50, 'x1': 500, 'text': '二、综合应用题'},
            {'y0': 330, 'x0': 50, 'x1': 150, 'text': '01.【解答】'},
            {'y0': 360, 'x0': 50, 'x1': 500, 'text': '应用题答案'},
        ]
    }

    (ocr_dir / 'page_010.json').write_text(json.dumps(question_page, ensure_ascii=False), encoding='utf-8')
    (ocr_dir / 'page_011.json').write_text(json.dumps(answer_page, ensure_ascii=False), encoding='utf-8')

    qa_pairs = {
        'total_pages': 20,
        'qa_pairs': [
            {
                'topic_title': '1.1.1 本节试题精选',
                'q_start': 10,
                'a_start': 11,
            }
        ]
    }
    qa_json = tmp_path / 'qa_pairs.json'
    qa_json.write_text(json.dumps(qa_pairs, ensure_ascii=False), encoding='utf-8')

    toc = [
        [1, '第1章 绪论', 1],
        [2, '1.1 小节', 5],
        [3, '1.1.1 本节试题精选', 10],
        [3, '1.1.1 答案与解析', 11],
    ]
    toc_json = tmp_path / 'toc.json'
    toc_json.write_text(json.dumps(toc, ensure_ascii=False), encoding='utf-8')

    return {
        'ocr_dir': ocr_dir,
        'qa_json': qa_json,
        'toc_json': toc_json,
    }


def run_script(args, cwd):
    """在项目根目录调用 scripts/ 下的脚本。"""
    cmd = [sys.executable] + args
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def test_build_pipeline(synthetic_course, tmp_path):
    project_root = Path(__file__).resolve().parent.parent
    raw = tmp_path / 'raw.json'
    post = tmp_path / 'post.json'
    out = tmp_path / 'out.json'

    # 1. parse_questions
    run_script([
        'scripts/parse_questions.py',
        '--ocr-dir', synthetic_course['ocr_dir'],
        '--qa-json', synthetic_course['qa_json'],
        '--toc-json', synthetic_course['toc_json'],
        '--output', raw,
        '--title', '测试题库',
        '--total-pages', '20',
    ], cwd=project_root)

    raw_data = json.loads(raw.read_text(encoding='utf-8'))
    assert raw_data['total_questions'] == 3
    assert len(raw_data['chapters']) == 1

    # 页脚噪音不应进入任何题干
    all_contents = [
        q.get('content', '')
        for ch in raw_data['chapters']
        for q in ch.get('questions', [])
    ]
    assert not any('2027年数据结构考研复习指导' in c for c in all_contents)

    # 2. post_process
    run_script(['scripts/post_process.py', raw, post], cwd=project_root)
    post_data = json.loads(post.read_text(encoding='utf-8'))
    ids = [q['id'] for ch in post_data['chapters'] for q in ch['questions']]
    assert 'X01' in ids and 'X02' in ids and 'A01' in ids

    # 3. reshape_by_l2
    run_script(['scripts/reshape_by_l2.py', synthetic_course['toc_json'], post, out], cwd=project_root)
    out_data = json.loads(out.read_text(encoding='utf-8'))
    assert out_data['total_questions'] == 3
    chapter_names = [ch['name'] for ch in out_data['chapters']]
    assert any('选择题' in name for name in chapter_names)
    assert any('解答题' in name for name in chapter_names)

    # 4. fix_questions
    run_script(['scripts/fix_questions.py', out], cwd=project_root)
    fixed_data = json.loads(out.read_text(encoding='utf-8'))
    choice_ch = next(ch for ch in fixed_data['chapters'] if '选择题' in ch['name'])
    app_ch = next(ch for ch in fixed_data['chapters'] if '解答题' in ch['name'])

    choice_qs = {q['id']: q for q in choice_ch['questions']}
    assert choice_qs['X01']['answer']['choice'] == 'C'
    assert choice_qs['X02']['answer']['choice'] == 'A'

    app_qs = {q['id']: q for q in app_ch['questions']}
    assert '应用题答案' in app_qs['A01']['answer']['explanation']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
