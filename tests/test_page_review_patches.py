import json
from pathlib import Path

BANK = Path(__file__).resolve().parents[1] / "math-bank"


def _load(course: str) -> dict:
    return json.loads((BANK / f"data-{course}.json").read_text(encoding="utf-8"))


def _q(course: str, chapter_part: str, qid: str) -> dict:
    data = _load(course)
    for chapter in data["chapters"]:
        if chapter_part in str(chapter.get("name") or "") and "选择" in str(
            chapter.get("name") or ""
        ):
            for question in chapter["questions"]:
                if question.get("id") == qid:
                    return question
    raise AssertionError(f"missing {course} {qid}")


def test_coa_trap_has_split_option_d():
    question = _q("coa", "异常和中断机制", "X01")
    assert "D" in question["options"]
    assert "内核" in question["options"]["D"]
    assert "异常情况" in question["options"]["C"]
    assert question["options"]["C"] != question["options"]["D"]


def test_coa_visible_registers_options_and_answer():
    question = _q("coa", "控制器的功能和工作原理", "X26")
    assert question["options"]["B"] != question["options"]["C"]
    assert "III" in question["options"]["C"]
    assert question["answer"]["choice"] == "B"


def test_ds_scan_star_stem_not_truncated():
    question = _q("ds", "栈和队列的应用", "X14")
    assert "当扫描到" in question["content"]
    assert "*" in question["content"]


def test_ds_circular_queue_end_pointers_not_duplicated():
    question = _q("ds", " · 队列 · ", "X22")
    assert question["options"]["A"] != question["options"]["B"]
    assert "end1==end2" in question["options"]["A"]
