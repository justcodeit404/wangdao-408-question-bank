#!/usr/bin/env python3
"""parse_patterns 模块的回归测试。"""

import pytest

from parse_patterns import (
    extract_answer_choice,
    QUESTION_HEADER_RE,
    OPTION_LINE_RE,
    PAGE_NOISE_RE,
    ANS_HEADER_RE,
    section_start_re,
    answer_header_re,
    chapter_header_re,
    is_page_noise,
    has_real_image_ref,
)


class TestExtractAnswerChoice:
    def test_single_choice(self):
        assert extract_answer_choice("01. C") == ("01", "C")
        assert extract_answer_choice("11. B") == ("11", "B")

    def test_multiple_choice(self):
        assert extract_answer_choice("06. B、D") == ("06", "BD")
        assert extract_answer_choice("11.B，A") == ("11", "BA")
        assert extract_answer_choice("16.B、E、C、D") == ("16", "BECD")

    def test_circled_number_prefix(self):
        assert extract_answer_choice("11.①B、②D") == ("11", "BD")

    def test_not_answer(self):
        # 题干中的 "B树" 不应被识别为答案
        assert extract_answer_choice("01. B树的特点") is None
        assert extract_answer_choice("A. 选项") is None


class TestQuestionHeaderRe:
    def test_match_zero_padded(self):
        m = QUESTION_HEADER_RE.match("01. 题目内容")
        assert m and m.group(1) == "1" and m.group(2) == "题目内容"

    def test_match_no_zero_pad(self):
        m = QUESTION_HEADER_RE.match("11. 题目内容")
        assert m and m.group(1) == "11"


class TestOptionLineRe:
    def test_match_options(self):
        assert OPTION_LINE_RE.match("A. 选项1").groups() == ("A", "选项1")
        assert OPTION_LINE_RE.match("B．选项2").groups() == ("B", "选项2")


class TestSectionRe:
    def test_section_start(self):
        r = section_start_re()
        assert r.match("1.2.3 本节试题精选")
        assert r.match("2.1 本节习题精选")
        assert not r.match("1.2.3 答案与解析")

    def test_answer_header(self):
        r = answer_header_re()
        assert r.match("1.2.3 答案与解析")
        assert r.match("2.1  答案与解析")
        assert not r.match("1.2.3 本节试题精选")

    def test_chapter_header(self):
        r = chapter_header_re()
        assert r.match("一、单项选择题")
        assert r.match("二、综合应用题")
        assert r.match("综合应用题")  # 兼容 OCR 丢失序号
        assert not r.match("01. 题目内容")


class TestAnsHeaderRe:
    def test_jieda_and_jiexi(self):
        assert ANS_HEADER_RE.match("01．【解答】").group(1) == "1"
        assert ANS_HEADER_RE.match("09.【解析】").group(1) == "9"
        assert ANS_HEADER_RE.match("06．【解析】").group(1) == "6"
        assert ANS_HEADER_RE.match("10．【解析】").group(1) == "10"
        assert not ANS_HEADER_RE.match("01. 题目内容")
        assert not ANS_HEADER_RE.match("09.【解析】算法思想")


class TestPageNoise:
    def test_simple_book_title(self):
        assert is_page_noise("2027年数据结构考研复习指导")
        assert is_page_noise("2027年操作系统考研复习指导")

    def test_with_page_number_prefix(self):
        # 页码 + 书名混在同一行
        assert is_page_noise("8 2027年数据结构考研复习指导")
        assert is_page_noise("  12  2027年计算机网络考研复习指导  ")

    def test_not_noise(self):
        # 正常题干/选项不应被误伤
        assert not is_page_noise("01. 2027年考研复习指导中的例题")
        assert not is_page_noise("A. 2027年数据结构考研复习指导")
        assert not is_page_noise("2027年数据结构考研复习指导及相关资料")
        assert not is_page_noise("数据结构考研复习指导")

    def test_regex_exposed(self):
        # 暴露原始正则，供需要精细控制的调用方使用
        assert PAGE_NOISE_RE.match("2027年计算机组成原理考研复习指导")


class TestHasRealImageRef:
    def test_right_figure_in_directed_graph(self):
        assert has_real_image_ref("在右图所示的有向图中，共有（）个强连通分量。")

    def test_as_shown_figure_in_directed_graph(self):
        assert has_real_image_ref(
            "已知带权有向图G的邻接矩阵如下图所示，请画出该带权有向图G。"
        )

    def test_graph_term_without_figure_marker(self):
        assert not has_real_image_ref(
            "对于一个有n个顶点的图：若是连通无向图，其边的个数至少为（）；"
            "若是强连通有向图，则其边的个数至少为（）。"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
