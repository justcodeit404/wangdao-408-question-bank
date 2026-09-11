#!/usr/bin/env python3
"""回归：对称/三角矩阵压缩存储公式 OCR 补丁不可再丢。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fix_questions as fq

ROOT = Path(__file__).resolve().parents[1]


def _load_ds():
    path = ROOT / "math-bank" / "data-ds.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _find(data, page: int, qid: str):
    for ch in data.get("chapters", []):
        for q in ch.get("questions", []):
            if q.get("page") == page and q.get("id") == qid:
                return q
    return None


class TestCuratedMatrixFormulaPatches:
    def test_patch_tables_present(self):
        assert ("ds", 110, "X08") in fq.CURATED_OPTION_PATCHES
        assert ("ds", 110, "X08") in fq.CURATED_TEXT_PATCHES

    def test_x03_content_and_option_a(self):
        # 2027 版原书 p104 第03题为对角元 A[i][i]，选项 A=(i+3)i/2
        # （旧 curated 补丁按 A[i][j]/(i+1)i/2+j 修正属旧版残留，2026-09-11 对照原书撤销）
        q = _find(_load_ds(), 109, "X03")
        assert q is not None
        assert "A[i][i]" in q["content"]
        assert "A[i][j]" not in q["content"]
        assert q["options"]["A"] == "(i+3)i/2"
        assert q["options"]["B"] == "(i+1)i/2"
        # 0-based 下三角按行：A[1][1] → 2
        assert "A[1][1]" in (q.get("answer") or {}).get("explanation", "")

    def test_x08_bk_and_option_b(self):
        q = _find(_load_ds(), 110, "X08")
        assert q is not None
        assert "B[k]" in q["content"]
        assert "aij" in q["content"]
        assert q["options"]["B"] == "(j-1)(2n-j+2)/2+i-j+1"
        assert not str(q["options"]["B"]).startswith("(Jj")
