#!/usr/bin/env python3
"""OCR 把数字 0 识别成 O / 把 1 识别成 l 的回归测试。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fix_questions as fq


class TestFixOcrZeroLetterO:
    def test_array_index_range(self):
        # 书中 OCR 常混用全角 ］；只断言下标 0 已纠正
        out1 = fq.fix_common_ocr_errors("若用数组A[O..5］实现循环队列")
        assert "A[0..5" in out1 and "A[O" not in out1
        out2 = fq.fix_common_ocr_errors("循环队列存储在数组A[O...n］中")
        assert "A[0...n" in out2
        out3 = fq.fix_common_ocr_errors("假设用A[o...n]实现循环队列")
        assert "A[0...n" in out3

    def test_nested_index(self):
        out = fq.fix_common_ocr_errors("而 A[O][O]存放于B[0]中")
        assert "A[0][0]" in out

    def test_degree_and_return(self):
        assert "入度为0" in fq.fix_common_ocr_errors("因为入栈或队列的都是入度为O的顶点")
        assert "返回0" in fq.fix_common_ocr_errors("否则，只返回O。要求：")
        assert "值都为0" in fq.fix_common_ocr_errors("front 和rear值都为O。入队时")

    def test_preserve_big_o(self):
        assert fq.fix_common_ocr_errors("时间复杂度为O(n)") == "时间复杂度为O(n)"
        # 0(n) 应先归一成 O(n)
        assert "O(n)" in fq.fix_common_ocr_errors("时间复杂度为0(n)")

    def test_preserve_stack_io(self):
        src = "以I和O分别表示入栈和出栈，则出入栈的操作序列可表示为由I和O组成的序列"
        out = fq.fix_common_ocr_errors(src)
        assert "I和O分别" in out
        assert "I和O组成" in out

    def test_option_and_zero(self):
        assert fq.fix_common_ocr_errors("3和O") == "3和0"
        assert fq.fix_common_ocr_errors("O和5") == "0和5"

    def test_letter_l_as_one(self):
        assert "(Q.rear+1)" in fq.fix_common_ocr_errors("(Q.rear+l) %MaxSize==Q.front")
        out = fq.fix_common_ocr_errors("可用（front+1）%（n+l）==rear")
        assert "n+1" in out and "n+l" not in out

    def test_missing_mod_percent(self):
        out = fq.fix_common_ocr_errors(
            "队首指针front=（front+1）6，每插入一个元素，队尾指针 rear=(rear+1）%6。"
        )
        assert "（front+1）%6" in out or "(front+1)%6" in out
        out2 = fq.fix_common_ocr_errors("若用（rear+1）（n+1）==front作为队满标志")
        assert "）%（n+1）" in out2 or ")%(n+1)" in out2


class TestFixOcrOnCircularQueueStem:
    def test_x07_stem(self):
        src = (
            "若用数组A[O..5］实现循环队列，且当前rear和front的值分别为1和5，当从队列\n"
            "中删除一个元素，再加入两个元素后，rear和front的值分别为（）。"
        )
        out = fq.fix_common_ocr_errors(src)
        assert "A[0..5" in out
        assert "A[O" not in out
