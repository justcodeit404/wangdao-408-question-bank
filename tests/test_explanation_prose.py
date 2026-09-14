"""有答案截图时隐藏 OCR 解析正文，避免与原书图重复。"""

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "math-bank" / "app.js"


def _eval_hide(cases: list[str]) -> list[bool]:
    src = APP_JS.read_text(encoding="utf-8")
    start = src.index("function shouldHideExplanationProse")
    end = src.index("function fillExplanation")
    script = (
        src[start:end]
        + "\n"
        + textwrap.dedent(
            f"""
            const cases = {json.dumps(cases, ensure_ascii=False)};
            const out = cases.map((t) => shouldHideExplanationProse(t));
            process.stdout.write(JSON.stringify(out));
            """
        )
    )
    tmp = Path(tempfile.gettempdir()) / "bank408-hide-expl-prose.js"
    tmp.write_text(script, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(tmp)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            check=False,
        )
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        raise AssertionError(
            f"node failed ({proc.returncode}):\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        )
    return json.loads(proc.stdout)


def test_fill_explanation_skips_prose_when_answer_image_present():
    js = APP_JS.read_text(encoding="utf-8")
    assert "function shouldHideExplanationProse" in js
    assert "const hideProse = shouldHideExplanationProse(raw);" in js
    assert "if (hideProse) continue;" in js


def test_should_hide_explanation_prose_cases():
    image_and_ocr, text_only, question_img, parse_img, empty = _eval_hide(
        [
            "答案图片：answer_crops/ds/page_204_X02_ans.jpg\n\n强连通图是有向图，与题意矛盾",
            "强连通图是有向图，与题意矛盾，选项 A 错误",
            "题目图片：crops/ds/page_203_X02.png\n\n解析仍需要这段文字",
            "解析图片：answer_crops/ds/page_010_X01_ans.jpg\n文字",
            "",
        ]
    )
    assert image_and_ocr is True
    assert text_only is False
    assert question_img is False
    assert parse_img is True
    assert empty is False
