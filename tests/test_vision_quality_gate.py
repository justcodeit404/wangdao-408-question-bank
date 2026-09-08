import hashlib
import json
import os
from pathlib import Path

import pytest

from vision_quality_gate import (
    DOUBAO_DEFAULT_BASE_URL,
    DOUBAO_DEFAULT_MODELS,
    OPEN_PLATFORM_MODELS,
    VisionConflictError,
    VisionInfrastructureError,
    _api_config,
    apply_patch_to_question,
    compare_results,
    index_batch_results,
    load_uids_file,
    require_distinct_models,
    retryable_conflict,
    run_gate,
    select_by_uids,
    select_full_candidates,
    select_rotating,
    source_hash,
    summarize_round,
)


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
    state = {
        "verified": {row["source_uid"]: source_hash(row["question"]) for row in rows},
        "epoch": 0,
    }
    selected = select_rotating(rows, state, 5, "round-2")
    assert len(selected) == 5
    assert state["epoch"] == 1


def test_dual_consensus_produces_exact_patch():
    row = _rows(1)[0]
    first = {
        "content": "新题干",
        "options": row["question"]["options"],
        "answer_choice": "C",
        "explanation": "新解析",
        "requires_image": False,
        "confidence": 0.99,
    }
    second = dict(first)
    result = compare_results(row, first, second, "C")
    assert result["status"] == "auto_fixed"
    assert result["patch"] == {"content": "新题干", "answer": {"explanation": "新解析"}}


def test_ocr_mismatch_does_not_block_dual_consensus():
    row = _rows(1)[0]
    result = {
        "content": "题干0",
        "options": row["question"]["options"],
        "answer_choice": "C",
        "explanation": "解析",
        "requires_image": False,
        "confidence": 0.99,
    }
    decided = compare_results(row, result, result, "A")
    assert decided["status"] == "verified"
    assert decided["consensus"]["answer.choice"] == "C"


def test_empty_answer_is_conflict():
    row = _rows(1)[0]
    result = {
        "content": "题干0",
        "options": row["question"]["options"],
        "answer_choice": "",
        "explanation": "解析",
        "requires_image": False,
        "confidence": 0.99,
    }
    with pytest.raises(VisionConflictError, match="答案"):
        compare_results(row, result, result, None)


def test_low_confidence_isolation():
    row = _rows(1)[0]
    result = {
        "content": "题干0",
        "options": row["question"]["options"],
        "answer_choice": "C",
        "explanation": "解析",
        "requires_image": False,
        "confidence": 0.4,
    }
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
    digest = summarize_round(
        [
            {"selection": "rotation", "status": "verified"},
            {"selection": "rotation", "status": "auto_fixed", "source_uid": "a"},
            {
                "selection": "rotation",
                "status": "held",
                "reason": "双模型字段冲突: content",
                "source_uid": "b",
                "course_key": "ds",
                "chapter": "绪论",
            },
            {
                "selection": "rotation",
                "status": "held",
                "reason": "双模型字段冲突: content",
                "source_uid": "c",
                "course_key": "ds",
                "chapter": "绪论",
            },
        ]
    )
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


def test_require_distinct_models_rejects_equal_pair():
    with pytest.raises(VisionInfrastructureError, match="不同视觉模型"):
        require_distinct_models(("same", "same"))


def test_api_config_prefers_doubao_ark_over_moonshot_and_strips_coding_plan(
    monkeypatch,
):
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.setenv("DOUBAO_API_KEY", "doubao-should-lose-to-ark")
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-should-lose")
    monkeypatch.setenv("KIMI_CODE_API_KEY", "coding-plan-must-not-win")
    monkeypatch.setenv("KIMI_CODE_KEY_FILE", "C:\\fake\\kimi.key")

    key, base, models = _api_config()

    assert key == "ark-test-key"
    assert base == DOUBAO_DEFAULT_BASE_URL
    assert models == DOUBAO_DEFAULT_MODELS
    assert models[0] != models[1]
    require_distinct_models(models)
    assert "KIMI_CODE_API_KEY" not in os.environ
    assert "KIMI_CODE_KEY_FILE" not in os.environ


def test_api_config_doubao_api_key_alias_and_custom_models(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("DOUBAO_API_KEY", "doubao-alias-key")
    monkeypatch.setenv("DOUBAO_BASE_URL", "https://ark.example/v3/")
    monkeypatch.setenv("DOUBAO_MODEL", "doubao-model-a")
    monkeypatch.setenv("DOUBAO_MODEL_B", "doubao-model-b")
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-should-lose")

    key, base, models = _api_config()

    assert key == "doubao-alias-key"
    assert base == "https://ark.example/v3"
    assert models == ("doubao-model-a", "doubao-model-b")
    require_distinct_models(models)


def test_api_config_doubao_equal_custom_models_fail_distinct_check(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("DOUBAO_API_KEY", "doubao-key")
    monkeypatch.setenv("DOUBAO_MODEL", "same-vision")
    monkeypatch.setenv("DOUBAO_MODEL_B", "same-vision")

    _, _, models = _api_config()
    assert models[0] == models[1]
    with pytest.raises(VisionInfrastructureError, match="不同视觉模型"):
        require_distinct_models(models)


def test_api_config_moonshot_when_no_doubao_ignores_coding_plan(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-key")
    monkeypatch.setenv("KIMI_CODE_API_KEY", "coding-plan-must-not-win")

    key, base, models = _api_config()

    assert key == "moonshot-key"
    assert base == "https://api.moonshot.cn/v1"
    assert models == OPEN_PLATFORM_MODELS
    assert models[0] != models[1]
    assert "KIMI_CODE_API_KEY" not in os.environ


def test_live_run_rejects_equal_models_not_only_full(monkeypatch):
    """Any live API path (rotation default) must refuse models[0]==models[1]."""
    monkeypatch.setattr(
        "vision_quality_gate._api_config",
        lambda: ("fake-key", "https://example.invalid/v1", ("same", "same")),
    )

    def boom_client():
        raise AssertionError("client_factory must not run after model gate")

    with pytest.raises(VisionInfrastructureError, match="不同视觉模型"):
        run_gate(client_factory=boom_client, full=False)


def test_full_selection_includes_hold_uid_with_matching_verified_hash():
    rows = _rows(3)
    hold_uid = rows[1]["source_uid"]
    verified = {row["source_uid"]: source_hash(row["question"]) for row in rows}
    selected = select_full_candidates(rows, verified, hold_uids={hold_uid})
    selected_uids = {row["source_uid"] for row in selected}
    assert hold_uid in selected_uids
    assert rows[0]["source_uid"] not in selected_uids
    assert rows[2]["source_uid"] not in selected_uids


def test_uids_file_selects_intersection_with_choice_rows(tmp_path: Path):
    rows = _rows(4)
    wanted = [rows[0]["source_uid"], rows[2]["source_uid"], "408:missing::ghost"]
    path = tmp_path / "uids.json"
    path.write_text(json.dumps(wanted), encoding="utf-8")
    uids = load_uids_file(path)
    selected = select_by_uids(rows, uids)
    assert [row["source_uid"] for row in selected] == [rows[0]["source_uid"], rows[2]["source_uid"]]
    assert load_uids_file(path) == {
        rows[0]["source_uid"],
        rows[2]["source_uid"],
        "408:missing::ghost",
    }
