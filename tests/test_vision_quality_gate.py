import hashlib

import pytest

from vision_quality_gate import VisionConflictError, apply_patch_to_question, compare_results, index_batch_results, retryable_conflict, select_rotating, source_hash, summarize_round


def _rows(count=20):
    return [
        {
            "source_uid": f"408:cs408-ds::章::X{index:02d}",
            "question": {
                "id": f"X{index:02d}",
                "content": f"题干{index}",
                "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
                "answer": {"choice": "C", "explanation": "解析"},
                "page": index + 1,
            },
        }
        for index in range(count)
    ]


def test_rotation_does_not_repeat_before_coverage():
    rows = _rows()
    state = {"verified": {}, "epoch": 0}
    first = select_rotating(rows, state, 5, "round-1")
    for row in first:
        state["verified"][row["source_uid"]] = source_hash(row["question"])
    second = select_rotating(rows, state, 5, "round-2")
    assert not ({row["source_uid"] for row in first} & {row["source_uid"] for row in second})


def test_rotation_starts_new_epoch_after_full_coverage():
    rows = _rows(5)
    state = {"verified": {row["source_uid"]: source_hash(row["question"]) for row in rows}, "epoch": 0}
    selected = select_rotating(rows, state, 5, "round-2")
    assert len(selected) == 5
    assert state["epoch"] == 1


def test_dual_consensus_produces_exact_patch():
    row = _rows(1)[0]
    first = {"content": "新题干", "options": row["question"]["options"], "answer_choice": "C", "explanation": "新解析", "requires_image": False, "confidence": 0.99}
    second = dict(first)
    result = compare_results(row, first, second, "C")
    assert result["status"] == "auto_fixed"
    assert result["patch"] == {"content": "新题干", "answer": {"explanation": "新解析"}}


def test_ocr_mismatch_does_not_block_dual_consensus():
    row = _rows(1)[0]
    result = {"content": "题干0", "options": row["question"]["options"], "answer_choice": "C", "explanation": "解析", "requires_image": False, "confidence": 0.99}
    decided = compare_results(row, result, result, "A")
    assert decided["status"] == "verified"
    assert decided["consensus"]["answer.choice"] == "C"


def test_empty_answer_is_conflict():
    row = _rows(1)[0]
    result = {"content": "题干0", "options": row["question"]["options"], "answer_choice": "", "explanation": "解析", "requires_image": False, "confidence": 0.99}
    with pytest.raises(VisionConflictError, match="答案"):
        compare_results(row, result, result, None)


def test_low_confidence_isolation():
    row = _rows(1)[0]
    result = {"content": "题干0", "options": row["question"]["options"], "answer_choice": "C", "explanation": "解析", "requires_image": False, "confidence": 0.4}
    with pytest.raises(VisionConflictError, match="置信度"):
        compare_results(row, result, result, "C")


def test_index_batch_results_uses_uid():
    mapped = index_batch_results(
        {"items": [{"uid": "b", "content": "乙"}, {"uid": "a", "content": "甲"}]},
        ["a", "b"],
    )
    assert mapped["a"]["content"] == "甲"
    assert mapped["b"]["content"] == "乙"


def test_index_batch_results_fills_missing_uid_in_order():
    mapped = index_batch_results(
        {"items": [{"content": "甲"}, {"content": "乙"}]},
        ["a", "b"],
    )
    assert mapped["a"]["content"] == "甲"
    assert mapped["b"]["content"] == "乙"


def test_summarize_round_counts_hold_reasons():
    digest = summarize_round([
        {"selection": "rotation", "status": "verified"},
        {"selection": "rotation", "status": "auto_fixed", "source_uid": "a"},
        {"selection": "rotation", "status": "held", "reason": "双模型字段冲突: content", "source_uid": "b", "course_key": "ds", "chapter": "绪论"},
        {"selection": "rotation", "status": "held", "reason": "双模型字段冲突: content", "source_uid": "c", "course_key": "ds", "chapter": "绪论"},
    ])
    assert digest["sample_total"] == 4
    assert digest["held"] == 2
    assert digest["hold_reasons"]["双模型字段冲突: content"] == 2


def test_field_conflict_does_not_retry():
    assert retryable_conflict(VisionConflictError("双模型字段冲突: content")) is False
    assert retryable_conflict(VisionConflictError("双模型字段冲突: explanation")) is False
    assert retryable_conflict(VisionConflictError("双模型置信度不足")) is True
    assert retryable_conflict(VisionConflictError("双模型未提取出答案")) is True


def test_patched_hash_does_not_resample():
    rows = _rows(5)
    patched_q = apply_patch_to_question(rows[0]["question"], {"content": "新题干"})
    rows[0] = {**rows[0], "question": patched_q}
    state = {"verified": {rows[0]["source_uid"]: source_hash(patched_q)}, "epoch": 0}
    selected = select_rotating(rows, state, 1, "round-2")
    assert rows[0]["source_uid"] not in {row["source_uid"] for row in selected}
