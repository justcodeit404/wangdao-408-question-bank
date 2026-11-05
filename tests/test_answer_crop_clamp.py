"""本轮 hold 题的答案段映射和裁剪锁只覆盖核对过的题。"""

from gen_answer_crops import ANSWER_PART_CLAMP, DS_SEG_QID_MAP, clamp_answer_parts


def test_ds_seg_map_lists_only_the_checked_hold_qids():
    assert DS_SEG_QID_MAP == {
        "5.1.4 本节试题精选": {"A02": "01"},
        "6.2.6 本节试题精选": {"A09": "08"},
        "6.4.6 本节试题精选": {
            "A03": "04",
            "A07": "08",
            "A09": "10",
            "A10": "11",
            "A13": "14",
        },
    }
    # 同节未核对的邻题不能被重挂。
    assert "A04" not in DS_SEG_QID_MAP["6.4.6 本节试题精选"]
    assert "A08" not in DS_SEG_QID_MAP["6.2.6 本节试题精选"]
    assert "A01" not in DS_SEG_QID_MAP["5.1.4 本节试题精选"]


def test_clamp_drops_summary_pages_and_locks_the_verified_edge():
    span = {
        "parts": [
            {"page": 266, "y0": 580, "y1": 1386},
            {"page": 267, "y0": 153, "y1": 1349},
            {"page": 268, "y0": 199, "y1": 1046},
            {"page": 269, "y0": 211, "y1": 1217},
        ]
    }
    locks = clamp_answer_parts("ds", "6.4.6 本节试题精选", "A13", span)
    assert [part["page"] for part in span["parts"]] == [266, 267]
    assert span["parts"][1]["y1"] == 216
    assert locks[267] == {"y1"}
    assert 266 not in locks


def test_clamp_ignores_questions_outside_this_round():
    span = {"parts": [{"page": 260, "y0": 1, "y1": 2}]}
    assert clamp_answer_parts("ds", "6.4.6 本节试题精选", "A04", span) == {}
    assert span["parts"] == [{"page": 260, "y0": 1, "y1": 2}]
    assert "ds\u241f6.4.6 本节试题精选\u241fA04" not in ANSWER_PART_CLAMP
