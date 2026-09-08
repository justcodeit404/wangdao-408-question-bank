"""Hold-bucket classifier for 408 drill recovery (todo 4)."""

from __future__ import annotations

from quality_hold import classify_hold_bucket


def _choice(
    *,
    options: dict[str, str] | None = None,
    content: str = "完整题干",
    choice: str = "A",
) -> dict[str, object]:
    opts = options if options is not None else {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    return {
        "type": "选择题",
        "content": content,
        "options": opts,
        "answer": {"choice": choice, "explanation": "解析"},
    }


def test_empty_options_is_structural() -> None:
    # Given: choice with empty options map
    question = _choice(options={})
    ledger = {
        "source_fidelity": "pending",
        "answer_validation": "pending",
        "reason_codes": [],
    }
    # When
    bucket = classify_hold_bucket(question, ledger)
    # Then
    assert bucket == "structural"


def test_source_fidelity_conflict_with_luna_answer_is_source_conflict() -> None:
    # Given: full ABCD choice; source conflict + luna_answer_conflict dual
    question = _choice()
    ledger = {
        "source_fidelity": "conflict",
        "answer_validation": "conflict",
        "reason_codes": ["luna_source_conflict", "luna_answer_conflict", "source_conflict"],
        "primary_hold_reason": "source_conflict",
    }
    # When
    bucket = classify_hold_bucket(question, ledger)
    # Then: dual luna still source_conflict, never answer_only
    assert bucket == "source_conflict"


def test_source_verified_answer_conflict_full_abcd_is_answer_only() -> None:
    # Given: structurally complete choice; source verified; answer conflict only
    question = _choice()
    ledger = {
        "source_fidelity": "verified",
        "answer_validation": "conflict",
        "reason_codes": ["luna_answer_conflict"],
        # live primary_hold_reason==answer_conflict count is 0 — must not be the detector
        "primary_hold_reason": "strict_hold",
    }
    # When
    bucket = classify_hold_bucket(question, ledger)
    # Then
    assert bucket == "answer_only"


def test_essay_is_non_choice() -> None:
    # Given: 解答题
    question = {
        "type": "解答题",
        "content": "证明题",
        "options": {},
        "answer": {"choice": "", "explanation": ""},
    }
    ledger = {
        "source_fidelity": "conflict",
        "answer_validation": "conflict",
        "reason_codes": ["luna_source_conflict"],
    }
    # When
    bucket = classify_hold_bucket(question, ledger)
    # Then
    assert bucket == "non_choice"


def test_stale_source_hash_reason_is_source_conflict_not_answer_only() -> None:
    # Given: source_fidelity verified but luna_stale_source_hash present
    question = _choice()
    ledger = {
        "source_fidelity": "verified",
        "answer_validation": "conflict",
        "reason_codes": ["luna_stale_source_hash", "strict_hold"],
    }
    # When / Then
    assert classify_hold_bucket(question, ledger) == "source_conflict"
