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
    start = src.index("const OCR_CODE_LINE_RE")
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


def _run_notes_slice(extra_js: str) -> str:
    src = APP_JS.read_text(encoding="utf-8")
    start = src.index("const OCR_CODE_LINE_RE")
    end = src.index("function getTotalPages")
    script = src[start:end] + "\n" + textwrap.dedent(extra_js)
    tmp = Path(__import__("tempfile").gettempdir()) / "bank408-notes-insert-runner.js"
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
    return proc.stdout


def test_conversion_inserts_after_its_own_image_and_marks_it():
    """识别结果锚定在图片后面（光标挪走也不插错位置），并把图片标成「已转」避免重复转换。"""
    raw = _run_notes_slice(
        """
        const ta = {
          value: '![图片](noteimg:a)\\n用户后写的一行',
          selectionStart: 0,
          selectionEnd: 0,
          focus() {},
          setSelectionRange(s, e) { this.selectionStart = s; this.selectionEnd = e; },
          setRangeText(text, s, e) {
            this.value = this.value.slice(0, s) + text + this.value.slice(e);
            this.selectionStart = this.selectionEnd = s + text.length;
          },
          dispatchEvent() { return true; },
        };
        const anchor = '![图片](noteimg:a)';
        insertAfterAnchor(ta, anchor, '$$x^2$$');
        markNoteImageConverted(ta, anchor);
        process.stdout.write(JSON.stringify(ta.value));
        """
    )
    assert json.loads(raw) == "![已转](noteimg:a)\n\n$$x^2$$\n用户后写的一行"


def test_notes_preview_wired_in_viewer():
    js = APP_JS.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    assert 'id="notesPreview"' in js
    assert "function prepareNoteMath" in js
    assert "renderNotePreview(preview, text)" in js
    # 图片预览：文本段仍走 prepareNoteMath + KaTeX；笔记里只存 noteimg: 短占位符，本体在分片 map
    assert "appendNoteTextSegment" in js
    assert "renderKatex(span)" in js
    assert "noteimg:" in js
    assert "storeNoteImage" in js
    assert "migrateLegacyNoteImages" in js
    assert "updatePreview" in js
    assert ".q-notes-preview" in css
    assert ".q-notes.has-note-preview .q-notes-preview" in css
    assert ".note-img" in css
    html = (ROOT / "math-bank" / "index.html").read_text(encoding="utf-8")
    assert "app.js?v=" in html
    import re

    m = re.search(r"__BANK_DATA_VER__='(\d+)'", html)
    assert m, "missing __BANK_DATA_VER__"
    ver = m.group(1)
    sw = (ROOT / "math-bank" / "sw.js").read_text(encoding="utf-8")
    assert f"wd408-ui-v{ver}" in sw
    assert f"sw.js?v={ver}" in js, "SW 注册串必须与 __BANK_DATA_VER__ 一致"


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


def test_prepare_math_reflows_prose_but_preserves_structure():
    prose, code, numbered, table = _eval_prepare(
        [
            "【2020统考真题】对于任意一棵高度为5且有10个结点的二叉树，若采用顺序存储结\n"
            "构保存，每个结点占1个存储单元，则存放该二叉树需要\n的存储单元数量至少是（）。",
            "下列算法的时间复杂度为（）。\nfor(i=0;i<n;i++)\n    sum++;",
            "下列说法正确的是（）。\nI．第一项\nII．第二项",
            "某程序如下表所示。\nA 1 2\nB 3 4",
        ]
    )
    assert "结\n构" not in prose
    assert "需要\n的" not in prose
    assert "for(i=0;i<n;i++)" in code and "\n" in code
    assert "I．第一项\nII．第二项" in numbered
    assert "某程序如下表所示。\nA 1 2" in table


def test_prepare_math_keeps_iv_and_answer_image_lines():
    iv, img = _eval_prepare(
        [
            "III. 高度为h（h>0）的完全二叉树对应的森林所含的树的个数一定是h\n"
            "IV. 一棵树中的叶子数一定等于与其对应的二叉树的叶子数",
            "只有满二叉树才具有性质III，如下图所示。\n"
            "答案图片：crops/ds/page_181_X01_forest.png\n"
            "在树转换为二叉树时，若有几个叶结点具有共同的双亲",
        ]
    )
    assert "\nIV. " in iv
    assert "是hIV." not in iv.replace(" ", "")
    glued = _eval_prepare(
        ["III. 高度为h（h>0）的完全二叉树对应的森林所含的树的个数一定是h IV. 一棵树中的叶子数"]
    )[0]
    assert "\nIV. " in glued
    assert "\n答案图片：crops/ds/page_181_X01_forest.png\n" in img


def test_prepare_math_keeps_unicode_superscripts_out_of_bare_tex():
    """¹ 不得变成裸 ^{1}，否则解析里 3ⁱ⁻¹ 会显示成 3ⁱ⁻^{1}。"""
    out = _eval_prepare(["这棵树的第i（i≥1）层最多有3ⁱ⁻¹个结点。则3⁰+3¹+…+3ʰ⁻¹=(3ʰ-1)/2"])[0]
    assert "^{1}" not in out
    assert "^{0}" not in out
    assert "ⁱ" in out
    assert "¹" in out


def test_prepare_math_wraps_bare_caret_and_log2():
    series, pow_n, log_n, log_paren = _eval_prepare(
        [
            r"最多为1+4+4^{h-1}",
            r"结点数最多为2^n-1-16=111",
            "地址线应为log24M=22根",
            "Wlog2(1+127)=28000",
        ]
    )
    assert r"$4^{h-1}$" in series
    assert r"$2^n-1$" in pow_n
    assert r"\log_2 4M" in log_n
    assert r"\log_2(1+127)" in log_paren
