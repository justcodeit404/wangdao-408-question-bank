"""408 题库笔记预览：失焦后走 KaTeX，裸 log_{2} 也能渲。"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "math-bank" / "app.js"
STYLES = ROOT / "math-bank" / "styles.css"


def _eval_prepare(cases: list[str]) -> list[str]:
    src = APP_JS.read_text(encoding="utf-8")
    start = src.index("function normalizeDisplayText")
    end = src.index("function getTotalPages")
    slice_js = src[start:end]
    script = (
        slice_js
        + "\n"
        + textwrap.dedent(
            f"""
            const cases = {json.dumps(cases, ensure_ascii=False)};
            const out = cases.map((t) => prepareNoteMath(t));
            process.stdout.write(JSON.stringify(out));
            """
        )
    )
    tmp = Path(__import__("tempfile").gettempdir()) / "bank408-notes-katex-runner.js"
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


def test_notes_preview_wired_in_viewer():
    js = APP_JS.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    assert 'id="notesPreview"' in js
    assert "function prepareNoteMath" in js
    assert "renderKatex(preview)" in js
    assert "preview.textContent = prepareNoteMath(text)" in js
    assert "updatePreview" in js
    assert ".q-notes-preview" in css
    assert ".q-notes.has-note-preview .q-notes-preview" in css
    html = (ROOT / "math-bank" / "index.html").read_text(encoding="utf-8")
    assert "app.js?v=39" in html
    sw = (ROOT / "math-bank" / "sw.js").read_text(encoding="utf-8")
    assert "wd408-ui-v39" in sw


def test_prepare_note_math_bare_log_and_delimited():
    bare, delimited, prose, dialog, paren = _eval_prepare(
        [
            "h=log_{2}i",
            r"$h=\log_2 n$",
            "同一层看层号",
            "dialog_box",
            r"\(\boldsymbol{h=\lfloor \log_2 n \rfloor +1}\)",
        ]
    )
    assert r"\log" in bare
    assert "log_{2}" not in bare.replace(r"\log_{2}", "")
    assert delimited.startswith("$h=")
    assert r"\log_2 n" in delimited
    assert prose == "同一层看层号"
    assert dialog == "dialog_box"
    assert paren.startswith(r"\(")
    assert r"\rfloor" in paren
