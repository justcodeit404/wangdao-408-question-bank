from pathlib import Path
import sys

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from auto_recrop_figs import (  # noqa: E402
    marker_band_box,
    ocr_box_coverage,
    question_ocr_bbox,
    question_fallback_box,
)


def _block(text, x0, y0, x1, y1):
    return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def test_marker_band_uses_space_after_wrapped_stem():
    gray = np.full((1100, 1100), 255, dtype=np.uint8)
    gray[705:795, 360:720] = 0  # the actual linked-list figure
    gray[811:835, 190:950] = 0  # numbered statements below the figure
    blocks = [
        _block("17．在如下图所示的双链表中，已知指针p指向结点A", 152, 629, 958, 661),
        _block("所指的结点B，则依次执行的语句序列可以是（）。", 197, 665, 652, 685),
        _block("↑d", 442, 699, 463, 720),
        _block("① q->next=p->next; ② q->prior=p;", 195, 811, 715, 834),
        _block("A. ①②④③", 194, 839, 312, 863),
    ]

    box, meta = marker_band_box(
        gray, blocks, [152, 629, 958, 863], "在如下图所示的双链表中"
    )

    assert meta["mode"] == "marker_band"
    assert box is not None
    assert box[1] < 710
    assert box[3] < 811


def test_marker_band_handles_figure_inside_long_answer_question():
    gray = np.full((700, 1100), 255, dtype=np.uint8)
    gray[210:325, 280:830] = 0
    blocks = [
        _block("18．假定采用带头结点的单链表保存单词", 154, 152, 950, 175),
        _block("存储映像如下图所示。", 197, 182, 905, 206),
        _block("str1", 286, 208, 322, 223),
        _block("str2", 290, 276, 325, 287),
        _block("设 str1 和 str2 分别指向两个单词所在单链表的头结点", 193, 329, 945, 360),
    ]

    box, _ = marker_band_box(
        gray, blocks, [154, 152, 954, 507], "存储映像如下图所示。"
    )

    assert box is not None
    assert box[1] <= 210
    assert box[3] < 329


def test_question_fallback_never_crosses_page_bounds():
    assert question_fallback_box([5, 7, 990, 1495], 1000, 1500) == (0, 0, 1000, 1500)


def test_question_fallback_expands_to_page_content_width_for_side_figure():
    assert question_fallback_box([152, 629, 800, 863], 1100, 1500) == (66, 619, 1034, 873)


def test_ocr_box_coverage_detects_a_text_strip():
    box = (100, 100, 700, 150)
    blocks = [_block("这是一整行被误当成图片的文字", 110, 105, 690, 140)]
    assert ocr_box_coverage(box, blocks) > 0.6


def test_question_ocr_bbox_extends_past_options_to_next_question():
    blocks = [
        _block("41．如下图所示，求最远距离", 170, 306, 970, 350),
        _block("A. 200m  B. 205m  C. 359m  D. 512m", 200, 391, 850, 425),
        _block("42．在下图所示的网络中", 170, 600, 970, 630),
    ]
    box, continues = question_ocr_bbox("X41", [172, 306, 971, 457], blocks, 1100, 1500)
    assert box == [172.0, 306.0, 971.0, 595.0]
    assert continues is False


def test_question_ocr_bbox_detects_bottom_page_continuation():
    blocks = [_block("46．帧的过程如下图所示", 172, 1300, 970, 1374)]
    box, continues = question_ocr_bbox("X46", [172, 93, 970, 1374], blocks, 1100, 1500)
    assert box[1] == 1300
    assert continues is True
