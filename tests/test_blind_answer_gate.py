from blind_answer_gate import normalize_choice, _blind_prompt


def test_normalize_choice_preserves_ordered_answers():
    assert normalize_choice("( B , E , C , D )") == "BECD"
    assert normalize_choice("答案：A") == "A"
    assert normalize_choice("") == ""


def test_blind_prompt_does_not_contain_source_answer_or_explanation():
    row = {
        "question": {
            "content": "某算法的时间复杂度是（）。",
            "options": {"A": "O(1)", "B": "O(n)"},
            "answer": {"choice": "B", "explanation": "答案必须被隐藏"},
        }
    }
    prompt = _blind_prompt(row)
    assert "答案必须被隐藏" not in prompt
    assert '"choice":"B"' in prompt  # JSON schema 示例，不是题库答案
