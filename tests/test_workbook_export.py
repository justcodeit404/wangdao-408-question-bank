"""PDF 做题本导出：408 当前筛选集合与纯题目渲染契约。"""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "math-bank" / "app.js"
INDEX = ROOT / "math-bank" / "index.html"


def _function(source: str, name: str) -> str:
    start = source.index("function %s(" % name)
    end = source.index("\n}\n", start)
    return source[start:end] + "\n}\n"


def test_workbook_renderer_excludes_answers_and_exports_filtered_order():
    source = APP.read_text(encoding="utf-8")
    functions = "\n".join(
        _function(source, name)
        for name in (
            "holdPageCropRef",
            "pageFallbackHtml",
            "questionStemHtml",
            "questionBelowHtml",
            "questionBodyHtml",
            "workbookQuestionHtml",
            "exportFilteredWorkbook",
            "renderQuestionBody",
        )
    )
    program = r"""
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function displayId(q) { return q.id.replace(/^[XA]/, ''); }
function pageLabel(q) { return '第 ' + q.page + ' 页'; }
function resolveQuestionImageRef(q) { return q.image_ref ? { src: q.image_ref } : null; }
function qualityForQuestion(q) { return q.id === 'X23' ? { overall: 'hold' } : null; }
function platformSourceUid(q) { return '408:cs408-ds::' + q.id; }
function imageHtml(ref) {
  return '<figure class="q-image"><img src="' + (ref.src || ref.cropped) + '"></figure>';
}
function renderOptionsHtml(q) {
  return '<div class="q-options">' + Object.entries(q.options || {})
    .map(([key, value]) => key + '. ' + value).join('；') + '</div>';
}
function renderSubHtml(q) {
  return (q.sub_questions || []).map((text, i) => '<div>(' + (i + 1) + ') ' + text + '</div>').join('');
}
function answerHtml() { throw new Error('answer renderer called'); }
function practiceAnswerHtml() { throw new Error('practice answer renderer called'); }
function bindDetailInteractions() { throw new Error('detail interactions called'); }
function bindPracticeInteractions() { throw new Error('practice interactions called'); }
function fillStemText(el, raw) { el.raw = raw; }
function renderKatex() {}
function optionGroupsOf(q) { return q.options; }
function flatOptionEntries(q) { return Object.entries(q.options || {}); }
function alert(message) { throw new Error(message); }
function makeContainer() {
  const qtext = { raw: '' };
  return {
    _html: '',
    set innerHTML(value) { this._html = value; },
    get innerHTML() {
      return this._html.replace(
        '<div class="q-text" data-role="qtext"></div>',
        '<div class="q-text" data-role="qtext">' + qtext.raw + '</div>'
      );
    },
    querySelector(selector) { return selector === '[data-role="qtext"]' ? qtext : null; },
    querySelectorAll() { return []; },
  };
}
let lastContainer = null;
const document = {
  title: '408 王道',
  createElement() { lastContainer = makeContainer(); return lastContainer; },
};
let captured = null;
const window = { ViewerPdfExport: { open(options) { captured = options; } } };
const fixture = {
  id: 'X23', chapter: '第1章 绪论', page: 12, type: '选择题',
  content: '408 题干 $x^2$', image_ref: 'question.png',
  options: { A: '甲', B: '乙' }, sub_questions: ['子题正文'],
  answer: { choice: 'SECRET_ANSWER', explanation: 'SECRET_EXPLANATION' },
  explanation: 'SECRET_EXPLANATION', answer_ref: 'SECRET_ANSWER_IMAGE',
};
const second = Object.assign({}, fixture, { id: 'X2', content: '先排版题' });
const filteredQuestions = [second, fixture];
""" + functions + r"""
const html = workbookQuestionHtml(fixture);
for (const expected of [
  '408 题干 $x^2$', 'question.png', 'A. 甲', '子题正文', '第1章 绪论',
  '未通过原书复核', 'page_crops/ds/page_012_X23.jpg',
]) {
  if (!html.includes(expected)) throw new Error('question content missing: ' + expected);
}
if (html.includes('SECRET_')) throw new Error('answer data leaked');
if (lastContainer._q !== undefined) throw new Error('print mode attached interactions');
exportFilteredWorkbook();
if (!captured || captured.questions !== filteredQuestions) throw new Error('wrong filtered question set');
if (captured.questions.map((q) => q.id).join(',') !== 'X2,X23') throw new Error('order changed');
if (captured.title !== '408 王道 · 当前筛选') throw new Error('wrong title');
if (captured.renderQuestion(fixture).includes('SECRET_')) throw new Error('renderer leaked');
console.log('ok');
"""
    result = subprocess.run(
        ["node", "-e", program], text=True, encoding="utf-8", capture_output=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_workbook_button_and_shared_script_are_wired():
    app = APP.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    assert 'id="btnExportWorkbook"' in index
    assert "pdf-export.js?v=" in index
    assert "addEventListener('click', exportFilteredWorkbook)" in app
    assert "questions: filteredQuestions" in app
