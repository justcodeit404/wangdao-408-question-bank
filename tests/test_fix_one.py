from fix_one import whitespace_only_change

QUESTION = {
    "id": "X01",
    "type": "选择题",
    "content": "经过以下栈的操作后，变量x的值为（）。\nInitStack(st);",
    "options": {"A": "1", "B": "2"},
    "answer": {"choice": "A", "explanation": "因为。"},
    "has_image": False,
    "image_ref": None,
    "q_pages": [1],
    "a_pages": [2],
}


def test_line_break_change_counts_as_layout() -> None:
    assert whitespace_only_change(QUESTION, {"content": "经过以下栈的操作后，变量x的值为（）。InitStack(st);"})


def test_answer_whitespace_also_counts_as_layout() -> None:
    assert whitespace_only_change(QUESTION, {"explanation": "因为。 "})


def test_real_text_change_needs_manual_review() -> None:
    assert not whitespace_only_change(QUESTION, {"content": "经过以下栈的操作后，变量x的值为（）。InitStack(st.pop);"})
    assert not whitespace_only_change(QUESTION, {"choice": "B"})


def test_noop_patch_is_not_layout_change() -> None:
    assert not whitespace_only_change(QUESTION, {"content": QUESTION["content"]})


def test_option_groups_always_goes_manual() -> None:
    assert not whitespace_only_change(QUESTION, {"option_groups": [{"label": "（1）", "options": {"A": "1"}}]})
