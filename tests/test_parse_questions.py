#!/usr/bin/env python3
"""parse_questions 核心解析逻辑的回归测试。"""
import pytest

import parse_questions as pq


def make_page(blocks):
    """用简单 block 列表构造 OCR page_data。"""
    return {'blocks': [{'y0': y, 'x0': x, 'x1': x + 100, 'y1': y + 20, 'text': t} for y, x, t in blocks]}


class TestBlockLayout:
    def test_get_block_text_sorts_by_y_then_x(self):
        page = make_page([
            (50, 10, 'B'),
            (10, 20, 'A2'),
            (10, 10, 'A1'),
            (50, 5, 'C'),
        ])
        items = pq.get_block_text(page)
        assert [it['text'] for it in items] == ['A1', 'A2', 'C', 'B']
        # 保留原始坐标
        assert items[0]['x0'] == 10 and items[0]['y0'] == 10

    def test_group_to_lines(self):
        page = make_page([
            (10, 10, '01.'),
            (10, 50, '第一题'),
            (20, 10, 'A.'),
            (20, 50, '选项A'),
            (25, 10, 'B.'),
            (25, 50, '选项B'),
        ])
        lines = pq.group_to_lines(pq.get_block_text(page), y_tol=6)
        assert len(lines) == 2
        assert lines[0]['texts'] == ['01.', '第一题']
        # 同一行内的 block 按 x 坐标排序
        assert lines[1]['texts'] == ['A.', 'B.', '选项A', '选项B']


class TestOptionParsing:
    def test_split_options_in_row(self):
        assert pq.split_options_in_row(['A. xxx', 'B. yyy', 'C. zzz']) == [
            ('A', 'xxx'), ('B', 'yyy'), ('C', 'zzz')
        ]

    def test_split_inline_options(self):
        assert pq.split_options_in_row(['A. xxx B. yyy C. zzz']) == [
            ('A', 'xxx'), ('B', 'yyy'), ('C', 'zzz')
        ]

    def test_extract_inline_options(self):
        opts = pq.extract_inline_options('错误的是（）。 A. xxx B. yyy C. zzz D. www')
        assert opts == {'A': 'xxx', 'B': 'yyy', 'C': 'zzz', 'D': 'www'}


class TestQuestionSpanParsing:
    def test_parse_single_page_choice_question(self):
        page = make_page([
            (10, 10, '1.1.1 本节试题精选'),
            (30, 10, '01. 题目内容'),
            (40, 10, 'A. 选项A'),
            (40, 200, 'B. 选项B'),
            (50, 10, '02. 第二题'),
            (60, 10, 'A. 选项1'),
            (60, 200, 'B. 选项2'),
            (80, 10, '1.1.1 答案与解析'),
            (90, 10, '01. A'),
            (100, 10, '解析一'),
            (110, 10, '02. B'),
            (120, 10, '解析二'),
        ])
        questions = pq.parse_questions_span([page], page_w=600)
        assert len(questions) == 2
        assert questions[0]['content'] == '题目内容'
        assert questions[0]['options'] == {'A': '选项A', 'B': '选项B'}
        assert questions[0]['type'] == '选择题'
        assert questions[1]['content'] == '第二题'

    def test_parse_app_question(self):
        page = make_page([
            (10, 10, '1.1.1 本节试题精选'),
            (30, 10, '01. 应用题题干'),
            (40, 10, '继续题干'),
            (60, 10, '1.1.1 答案与解析'),
            (70, 10, '二、综合应用题'),
            (80, 10, '01.【解答】'),
            (90, 10, '应用题答案'),
        ])
        questions = pq.parse_questions_span([page], page_w=600)
        assert len(questions) == 1
        assert questions[0]['type'] == '综合应用题'

    def test_parse_question_bbox(self):
        page = make_page([
            (10, 10, '1.1.1 本节试题精选'),
            (30, 10, '01. 题目内容'),
            (40, 10, 'A. 选项A'),
            (40, 200, 'B. 选项B'),
        ])
        questions = pq.parse_questions_span([page], page_w=600)
        assert len(questions) == 1
        assert 'bbox' in questions[0]
        x0, y0, x1, y1 = questions[0]['bbox']
        assert x0 == 10 and y0 == 30
        assert x1 == 300 and y1 == 60


class TestAnswerPageParsing:
    def test_parse_choice_answers(self):
        page = make_page([
            (10, 10, '1.1.1 答案与解析'),
            (20, 10, '一、单项选择题'),
            (30, 10, '01. A'),
            (40, 10, '解析一'),
            (50, 10, '02. B'),
            (60, 10, '解析二'),
        ])
        ans = pq.parse_answer_page(page)
        assert 'choice' in ans and 'app' in ans
        assert ans['choice']['01']['choice'] == 'A'
        assert ans['choice']['02']['choice'] == 'B'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
