from normalize_spaces import normalize_text


def test_sentence_break_is_kept() -> None:
    text = "经过以下栈的操作后，变量x的值为（）。\nInitStack(st);"
    assert normalize_text(text)[0] == text


def test_wrap_after_enumeration_comma_is_joined() -> None:
    text = "其中有进位/借位标志CF、零标志ZF、\n符号标志SF和溢出标志OF。"
    assert "\n" not in normalize_text(text)[0]


def test_fenced_code_is_untouched() -> None:
    text = "```\nint a = 1;\nreturn a;\n```"
    assert normalize_text(text)[0] == text
