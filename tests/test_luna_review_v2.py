from luna_review_v2 import (
    NON_CHOICE,
    OBJECTIVE,
    apply_v2_fields,
    certification_profile,
    primary_hold_reason,
)


def test_profile_splits_choice_and_essay():
    assert certification_profile({"type": "选择题"}) == OBJECTIVE
    assert certification_profile({"type": "解答题"}) == NON_CHOICE


def test_primary_reason_is_exclusive_and_drops_blanket_human_hold():
    item = {
        "overall": "hold",
        "reason_codes": ["human_hold", "luna_source_conflict", "luna_answer_conflict"],
        "evidence": {},
    }
    apply_v2_fields(item, {"type": "选择题"})
    assert item["certification_profile"] == OBJECTIVE
    assert item["primary_hold_reason"] == "source_conflict"
    assert "human_hold" not in item["reason_codes"]
    assert (
        primary_hold_reason({"reason_codes": ["structural_check"]})
        == "structural_error"
    )
    assert (
        primary_hold_reason({"reason_codes": ["human_hold"], "evidence": {}})
        == "strict_hold"
    )
    assert (
        primary_hold_reason(
            {"reason_codes": ["human_hold"], "evidence": {"human_reviewer": "owner"}}
        )
        == "human_hold"
    )
