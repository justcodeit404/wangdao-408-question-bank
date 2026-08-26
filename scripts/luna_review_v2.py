#!/usr/bin/env python3
"""luna-review-v2 protocol helpers. No model calls."""

from __future__ import annotations

from typing import Any, Mapping

PROTOCOL = "luna-review-v2"
MODEL = "gpt-5.6-luna"
OBJECTIVE = "objective_full"
NON_CHOICE = "non_choice_source_answer"
HOLD_REASONS = (
    "structural_error",
    "source_conflict",
    "answer_conflict",
    "source_unreadable",
    "model_conflict",
    "strict_hold",
    "human_hold",
)


def certification_profile(question: Mapping[str, Any]) -> str:
    qtype = str(question.get("type") or "")
    return NON_CHOICE if "选择" not in qtype else OBJECTIVE


def primary_hold_reason(item: Mapping[str, Any]) -> str:
    """One exclusive reason. human_hold only if evidence says a person reviewed."""
    codes = {
        str(code) for code in (item.get("reason_codes") or []) if str(code).strip()
    }
    raw_evidence = item.get("evidence")
    evidence = raw_evidence if isinstance(raw_evidence, Mapping) else {}
    human = str(evidence.get("human_reviewer") or "").strip()
    if (
        "structural_check" in codes
        or "duplicate_uid" in codes
        or "structural_error" in codes
    ):
        return "structural_error"
    if any(
        code in codes
        for code in (
            "luna_source_conflict",
            "source_conflict",
            "ocr_answer_mismatch",
            "ocr_stem_or_options_mismatch",
        )
    ):
        return "source_conflict"
    if "luna_answer_conflict" in codes or "answer_conflict" in codes:
        return "answer_conflict"
    if "source_unreadable" in codes:
        return "source_unreadable"
    if "model_conflict" in codes:
        return "model_conflict"
    if human:
        return "human_hold"
    return "strict_hold"


def apply_v2_fields(item: dict[str, Any], question: Mapping[str, Any]) -> None:
    item["certification_profile"] = certification_profile(question)
    if item.get("overall") == "hold":
        item["primary_hold_reason"] = primary_hold_reason(item)
        item["reason_codes"] = sorted(
            {code for code in (item.get("reason_codes") or []) if code != "human_hold"}
            | {item["primary_hold_reason"]}
        )
    else:
        item.pop("primary_hold_reason", None)
