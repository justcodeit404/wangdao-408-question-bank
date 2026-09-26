#!/usr/bin/env python3
"""回归：完全二叉树最少结点数题目的 OCR 指数补丁不可丢。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fix_questions as fq


ROOT = Path(__file__).resolve().parents[1]


def _load_ds():
    return json.loads((ROOT / "math-bank" / "data-ds.json").read_text(encoding="utf-8"))


def _find(data, page: int, qid: str):
    for chapter in data.get("chapters", []):
        for question in chapter.get("questions", []):
            if question.get("page") == page and question.get("id") == qid:
                return question
    return None


def test_complete_binary_tree_formula_patch_is_registered():
    assert ("ds", 138, "X11") in fq.CURATED_OPTION_PATCHES
    assert ("ds", 138, "X11") in fq.CURATED_TEXT_PATCHES
    assert ("ds", 139, "X20") in fq.CURATED_OPTION_PATCHES
    assert ("ds", 139, "X20") in fq.CURATED_TEXT_PATCHES


def test_complete_binary_tree_formula_is_correct_in_generated_bank():
    question = _find(_load_ds(), 138, "X11")
    assert question is not None
    assert question["options"] == {
        "A": "$2^h$",
        "B": "$2^h+1$",
        "C": "$2^{h-1}$",
        "D": "$2^h-1$",
    }
    assert question["answer"]["choice"] == "C"
    explanation = question["answer"]["explanation"]
    assert "$2^{h-1}-1$" in explanation
    assert "$(2^{h-1}-1)+1=2^{h-1}$" in explanation


def test_same_level_floor_log_is_correct_in_generated_bank():
    question = _find(_load_ds(), 139, "X20")
    assert question is not None
    assert question["options"] == {
        "A": "⌊log₂p⌋ = ⌊log₂q⌋",
        "B": "log₂p=log₂q",
        "C": "⌊log₂p⌋ + 1= ⌊log₂q⌋",
        "D": "⌊log₂p⌋ = ⌊log₂q⌋ + 1",
    }
    assert question["answer"]["choice"] == "A"
    explanation = question["answer"]["explanation"]
    assert "⌊log₂i⌋+1" in explanation
    assert "⌊log₂p⌋=⌊log₂q⌋" in explanation
    assert "Llog" not in explanation
    assert "[log2p" not in str(question["options"])


def test_full_binary_tree_exponent_patch_is_registered():
    assert ("ds", 139, "X24") in fq.CURATED_OPTION_PATCHES
    assert ("ds", 139, "X24") in fq.CURATED_TEXT_PATCHES
    assert fq.CURATED_OPTION_PATCHES[("ds", 139, "X24")]["D"] == "$n=2^h-1$"


def test_full_binary_tree_n_equals_two_to_the_h():
    question = _find(_load_ds(), 139, "X24")
    assert question is not None
    assert question["options"] == {
        "A": "n=h+m",
        "B": "n+m=2h",
        "C": "m=h-1",
        "D": "$n=2^h-1$",
    }
    assert question["answer"]["choice"] == "D"
    explanation = question["answer"]["explanation"]
    assert "2^h-1" in explanation
    assert "2^{h-1}" in explanation
    assert question["options"]["D"] != "n=2h-1"
