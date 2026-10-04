"""题干 markdown 管道表渲染：多表、转义、单元格内 KaTeX。

通过 node 抽取 app.js 里的纯函数切片 + fillStemText/renderKatex，
用最小 FakeEl DOM 桩验证输出结构。
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "math-bank" / "app.js"

DOM_SHIM = r"""
function unescapeHtml(s) {
  return String(s)
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
}

class FakeEl {
  constructor(tag) {
    this.tag = tag || 'div';
    this._text = '';
    this._html = '';
    this._prose = [];
    this._cells = [];
    this._hasTable = false;
  }
  set textContent(v) {
    this._text = String(v);
    this._html = '';
    this._prose = [];
    this._cells = [];
    this._hasTable = false;
  }
  get textContent() { return this._text; }
  set innerHTML(v) {
    this._html = String(v);
    this._text = '';
    this._hasTable = /<table>/.test(this._html);
    this._prose = [];
    this._codes = [];
    const proseCount = (this._html.match(/class="stem-prose"/g) || []).length;
    for (let k = 0; k < proseCount; k++) this._prose.push(new FakeEl('div'));
    const codeCount = (this._html.match(/class="stem-code"/g) || []).length;
    for (let k = 0; k < codeCount; k++) this._codes.push(new FakeEl('pre'));
    this._cells = [];
    const cellRe = /<(th|td)>([\s\S]*?)<\/\1>/g;
    let m;
    while ((m = cellRe.exec(this._html))) {
      const c = new FakeEl(m[1]);
      c._text = unescapeHtml(m[2]);
      this._cells.push(c);
    }
  }
  get innerHTML() { return this._html; }
  querySelector(sel) {
    if (sel === 'table') return this._hasTable ? { tag: 'table' } : null;
    return null;
  }
  querySelectorAll(sel) {
    if (sel === '.stem-prose') return this._prose;
    if (sel === '.stem-code') return this._codes || [];
    if (sel === '.stem-table th, .stem-table td') return this._cells;
    if (sel === '.stem-prose, .stem-table th, .stem-table td') {
      return this._prose.concat(this._cells);
    }
    return [];
  }
}

global.window = { katex: true };
global.katex = {
  renderToString(latex, opts) {
    return 'MATH[' + (opts && opts.displayMode ? 'D' : 'I') + ':' + latex + ']';
  },
};
"""

RUNNER = r"""
const results = CASES.map((input) => {
  const el = new FakeEl('div');
  fillStemText(el, input);
  const usedTextPath = el._html === '' && el._text.length > 0;
  const rawHtml = el._html;
  const textAfterFill = el._text;
  const proseTexts = el._prose.map((p) => p._text);
  const codeTexts = (el._codes || []).map((c) => c._text);
  renderKatex(el);
  return {
    usedTextPath,
    rawHtml,
    proseTexts,
    codeTexts,
    tableCount: (rawHtml.match(/<table>/g) || []).length,
    cellsHtml: el._cells.map((c) => c.innerHTML || c._text),
    proseHtml: el._prose.map((p) => p.innerHTML || p._text),
    finalText: el._text,
    finalHtml: el._html,
    textAfterFill,
  };
});
process.stdout.write(JSON.stringify(results));
"""


def _eval_fill(cases: list[str]) -> list[dict]:
    src = APP_JS.read_text(encoding="utf-8")
    slice_a = src[
        src.index("const OCR_CODE_LINE_RE") : src.index("function getTotalPages")
    ]
    slice_b = src[
        src.index("function isPipeRow") : src.index("function renderQuestionBody")
    ]
    slice_c = src[src.index("function renderKatex") : src.index("function escapeHtml")]
    slice_d = src[
        src.index("function escapeHtml") : src.index(
            "// ========================\n// Events"
        )
    ]
    script = (
        slice_a
        + "\n"
        + slice_b
        + "\n"
        + slice_c
        + "\n"
        + slice_d
        + "\n"
        + DOM_SHIM
        + "\n"
        + "const CASES = "
        + json.dumps(cases, ensure_ascii=False)
        + ";\n"
        + RUNNER
    )
    tmp = Path(__import__("tempfile").gettempdir()) / "bank408-stem-tables-runner.js"
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


def test_single_table_renders_with_prose():
    (res,) = _eval_fill(["如下表所示。\n| A | B |\n| --- | --- |\n| 1 | 2 |"])
    assert not res["usedTextPath"]
    assert res["tableCount"] == 1
    assert "<th>A</th><th>B</th>" in res["rawHtml"]
    assert "<td>1</td><td>2</td>" in res["rawHtml"]
    assert res["proseTexts"] == ["如下表所示。"]


def test_two_tables_in_one_stem():
    (res,) = _eval_fill(["t1\n| a |\n| - |\n| 1 |\nmid\n| b |\n| - |\n| 2 |\ntail"])
    assert res["tableCount"] == 2
    assert res["proseTexts"] == ["t1", "mid", "tail"]


def test_cell_html_is_escaped():
    (res,) = _eval_fill(["| a |\n| - |\n| <script>alert(1)</script> |"])
    assert "<script>" not in res["rawHtml"]
    assert "&lt;script&gt;" in res["rawHtml"]
    # 渲染后也不允许出现未转义的标签
    assert all("<script>" not in cell for cell in res["cellsHtml"])


def test_separator_row_dropped():
    (res,) = _eval_fill(["| a |\n| --- |\n| 1 |"])
    assert "---" not in res["rawHtml"]
    assert res["tableCount"] == 1


def test_empty_cell_becomes_nbsp():
    (res,) = _eval_fill(["| a | b |\n| - | - |\n|  | 2 |"])
    assert "<td>&nbsp;</td>" in res["rawHtml"]


def test_no_table_uses_textcontent_path():
    (res,) = _eval_fill(["这是一段普通题干。"])
    assert res["usedTextPath"]
    assert res["textAfterFill"] == "这是一段普通题干。"


def test_uneven_columns_still_table():
    (res,) = _eval_fill(["| a | b | c |\n| - | - |\n| 1 |"])
    assert res["tableCount"] == 1
    assert res["rawHtml"].count("<th>") == 3


def test_katex_runs_inside_table_cells():
    (res,) = _eval_fill([r"| 公式 | 值 |" + "\n| - | - |\n| $h=\\log_2 n$ | 3 |"])
    assert any("MATH[I:" in cell and "\\log_2 n" in cell for cell in res["cellsHtml"])


def test_katex_runs_in_prose_between_tables():
    (res,) = _eval_fill(
        [r"| a |" + "\n| - |\n| 1 |\n结论 $n^{2}$ 成立。\n| b |\n| - |\n| 2 |"]
    )
    assert res["tableCount"] == 2
    assert any("MATH[I:" in p and "n^{2}" in p for p in res["proseHtml"])


def test_unicode_superscript_wraps_once_and_stays_inline():
    # 回归：n² 曾被 n²→$n^{2}$ 再被 \bn\^{2} 二次包成 $$n^{2}$$（块级居中）
    (res,) = _eval_fill(["n²"])
    assert res["textAfterFill"] == "$n^{2}$"
    assert "MATH[I:n^{2}]" in res["finalHtml"]
    assert "MATH[D:" not in res["finalHtml"]


def test_unicode_superscript_cube_wraps_once():
    (res,) = _eval_fill(["n³"])
    assert res["textAfterFill"] == "$n^{3}$"
    assert "MATH[I:n^{3}]" in res["finalHtml"]
    assert "MATH[D:" not in res["finalHtml"]


def test_literal_superscript_wraps_once():
    (res,) = _eval_fill(["n^{2}"])
    assert res["textAfterFill"] == "$n^{2}$"
    assert "MATH[D:" not in res["finalHtml"]


def test_collapsed_c_snippet_is_a_code_block():
    (res,) = _eval_fill(
        ["【2025统考真题】在32位计算机上执行下列C语言代码段后，ui的值是（）。short si= -32767;unsigned int ui=si;"]
    )
    assert not res["usedTextPath"]
    assert '<pre class="stem-code">' in res["rawHtml"]
    assert res["codeTexts"] == ["short si = -32767;\nunsigned int ui = si;"]
    assert res["proseTexts"] == ["【2025统考真题】在32位计算机上执行下列C语言代码段后，ui的值是（）。"]
    assert "<script>" not in res["rawHtml"]


def test_for_header_semicolons_stay_on_one_line():
    (res,) = _eval_fill(
        ["时间复杂度是。int count=0, i, j; for(i=1; i*i<=n; i++) for(j=1; j<=i; j++) count ++;"]
    )
    code = res["codeTexts"][0]
    assert "for(i = 1; i*i<=n; i++)" in code
    assert code.startswith("int count = 0, i, j;")


def test_multiline_if_stays_one_block():
    src = '如下：\nint si=65536;\nif(i<=j-1) printf("王道");\nelse printf("计算机教育");\n结束。'
    (res,) = _eval_fill([src])
    assert len(res["codeTexts"]) == 1
    assert "if(i<=j-1) printf(\"王道\");" in res["codeTexts"][0]
    assert "else printf(\"计算机教育\");" in res["codeTexts"][0]
    assert res["proseTexts"][0].startswith("如下：")
    assert res["proseTexts"][-1] == "结束。"


def test_type_word_inside_chinese_is_not_code():
    (res,) = _eval_fill(["假定编译器规定int型和short型长度分别为32位。"])
    assert res["usedTextPath"]
    assert res["codeTexts"] == []
