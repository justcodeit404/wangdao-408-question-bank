from ocr_equivalence import answers_equivalent, source_texts_equivalent
from luna_source_evidence import _strict_or_near_match


def test_source_texts_ignore_whitespace_and_soft_wraps():
    assert source_texts_equivalent("存放该二叉树需要的存储单元", "存放该二叉\n树需要 的存储单元")


def test_source_texts_ignore_cn_en_punctuation_and_option_markers():
    assert source_texts_equivalent("正确的是（）。", "正确的是().")
    assert source_texts_equivalent("A. 顺序存储", "Ａ、顺序存储")


def test_source_texts_ignore_latex_outer_delimiters():
    assert source_texts_equivalent(r"$O(n)$", r"\(O(n)\)")
    assert source_texts_equivalent(r"\[n^2\]", r"$n^2$")


def test_source_texts_keep_numbers_operators_and_negation():
    assert not source_texts_equivalent("n=2m-1", "n=2m+1")
    assert not source_texts_equivalent("不是完全二叉树", "是完全二叉树")
    assert not source_texts_equivalent("x_1", "x_2")


def test_source_texts_keep_option_content_changes():
    assert not source_texts_equivalent("只有左子树", "只有右子树")


def test_source_texts_glyph_confusions_not_format_equivalent():
    """O/0, l/1, roman IIl noise are semantic — not format-only OCR drift."""
    assert source_texts_equivalent("O(n)", "0(n)") is False
    assert source_texts_equivalent("n-l", "n-1") is False
    assert source_texts_equivalent("III", "IIl") is False
    assert source_texts_equivalent("III", "IIL") is False
    # substring rule used to treat shorter pure-I run as format-eq of IIIIl
    assert source_texts_equivalent("III", "IIIIl") is False
    # wrap/punct still format-only
    assert source_texts_equivalent("正确的是（）。", "正确的是().") is True


def test_source_texts_glyph_gate_spares_chinese_prose():
    """Must not treat every Latin letter/digit in Chinese stems as conflict."""
    assert source_texts_equivalent(
        "若某算法最坏时间复杂度为O(n)，则正确的是（）。",
        "若某算法最坏时间复杂度为O(n)，则正确的是().",
    )
    assert source_texts_equivalent("第1章概述", "第1章概述")


def test_strict_or_near_match_uses_format_equivalence():
    assert _strict_or_near_match("正确的是（）。", "正确的是().")
    assert not _strict_or_near_match("不是栈", "是栈")


def test_answers_ignore_multiselect_order_but_keep_set():
    assert answers_equivalent("C、A", "AC")
    assert answers_equivalent("B", "b")
    assert not answers_equivalent("A", "AB")
    assert not answers_equivalent("A", "B")
    assert not answers_equivalent("", "A")
