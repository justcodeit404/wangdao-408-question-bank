#!/usr/bin/env python3
"""Format-only OCR/published text equivalence. Semantic diffs stay conflicts."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

PUNCT_TABLE = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "、": ",",
        "－": "-",
        "−": "-",
        "–": "-",
        "—": "-",
        "／": "/",
        "＝": "=",
        "＋": "+",
        "×": "*",
        "·": "*",
        "＊": "*",
    }
)
OPTION_PREFIX_RE = re.compile(r"^[a-gａ-ｇ]\s*[.．。、:：)]\s*", re.IGNORECASE)
LATEX_WRAP_RE = re.compile(r"^(\$\$|\$|\\\(|\\\[)(.*)(\$\$|\$|\\\)|\\\])$")
NUMBER_RE = re.compile(r"\d+(?:[.]\d+)?")
OPERATOR_RE = re.compile(r"[+\-*/=<>≤≥%~^|&]")
NEGATION_RE = re.compile(r"不|非|无|未|没|not|no|never")
CHOICE_RE = re.compile(r"[A-G]")
# After casefold: complexity O( vs digit 0(, code-like l vs 1, roman i/l runs.
_COMPLEXITY_O_RE = re.compile(r"(?<![a-z0-9])o\(")
_COMPLEXITY_ZERO_RE = re.compile(r"(?<![a-z0-9])0\(")
_CODELIKE_L_RE = re.compile(
    r"(?<=[a-z0-9])l(?=[a-z0-9\-])|(?<=[a-z0-9\-])l(?=[a-z0-9])|(?<=[a-z0-9\-])l$"
)
_CODELIKE_ONE_RE = re.compile(r"(?<=[a-z])1(?=[a-z0-9\-])|(?<=[a-z0-9\-])1(?=[a-z])|(?<=[a-z\-])1$")
_ROMAN_IL_RUN_RE = re.compile(r"[il]{2,}")


def _strip_latex_wrap(value: str) -> str:
    current = value
    for _ in range(3):
        match = LATEX_WRAP_RE.fullmatch(current)
        if not match:
            return current
        current = match.group(2)
    return current


def canonical_source_text(value: Any) -> str:
    """Collapse format-only differences; keep digits, operators, and words."""
    text = unicodedata.normalize("NFKC", str(value or "")).translate(PUNCT_TABLE)
    text = OPTION_PREFIX_RE.sub("", text.strip())
    text = _strip_latex_wrap(text.strip())
    return "".join(text.casefold().split())


def _tokens(value: str) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    return (
        tuple(NUMBER_RE.findall(value)),
        tuple(OPERATOR_RE.findall(value)),
        len(NEGATION_RE.findall(value)),
    )


def _glyph_profile(value: str) -> tuple[int, int, int, int, tuple[str, ...]]:
    """Fingerprint OCR-confusable glyphs; unequal profiles ⇒ semantic conflict."""
    return (
        len(_COMPLEXITY_O_RE.findall(value)),
        len(_COMPLEXITY_ZERO_RE.findall(value)),
        len(_CODELIKE_L_RE.findall(value)),
        len(_CODELIKE_ONE_RE.findall(value)),
        tuple(_ROMAN_IL_RUN_RE.findall(value)),
    )


def _glyphs_conflict(left: str, right: str) -> bool:
    """True when O/0, code-like l/1, or roman IIl-style runs disagree."""
    return _glyph_profile(left) != _glyph_profile(right)


def source_texts_equivalent(left: Any, right: Any) -> bool:
    """True only when remaining differences are format, not meaning."""
    a = canonical_source_text(left)
    b = canonical_source_text(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if _tokens(a) != _tokens(b):
        return False
    # Substring near-match must not hide glyph confusions (III ⊂ IIIIl, etc.).
    if _glyphs_conflict(a, b):
        return False
    return a in b or b in a


def normalize_choice_set(value: Any) -> str | None:
    letters = CHOICE_RE.findall(unicodedata.normalize("NFKC", str(value or "")).upper())
    return "".join(sorted(set(letters))) or None


def answers_equivalent(left: Any, right: Any) -> bool:
    """Multi-select compares the letter set; empty never matches a real choice."""
    a = normalize_choice_set(left)
    b = normalize_choice_set(right)
    return bool(a) and a == b
