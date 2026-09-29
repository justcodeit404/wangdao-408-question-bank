// ========================
// Theme
// ========================
(function initTheme() {
  const stored = localStorage.getItem('mathbank_theme');
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = stored || (prefersDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', theme);
})();

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('mathbank_theme', next); } catch(e) {}
}

document.getElementById('themeToggle').addEventListener('click', toggleTheme);

// ========================
// 408 现阶段只展示选择题（不删源数据，在数据加载层过滤）
// 纯逻辑见 choice-only.js（ChoiceOnlyView）；契约：platform-v2 test_choice_type_contract
// ========================
const CHOICE_ONLY_MODE = true;
const _COV = (typeof window !== 'undefined' && window.ChoiceOnlyView) ? window.ChoiceOnlyView : null;
if (!_COV) {
  console.error('[bank-408] choice-only.js 未加载，选择题过滤不可用');
}
const CHOICE_QUESTION_TYPES = _COV
  ? _COV.CHOICE_QUESTION_TYPES
  : new Set(['single_choice', 'multiple_choice', 'ordered_choice', '选择题', 'multiple', 'multi', 'single', '单选', '多选']);
function isChoiceQuestionType(type) {
  return _COV ? _COV.isChoiceQuestionType(type) : false;
}
function filterCourseDataToChoices(courseData) {
  if (!_COV) return courseData;
  const filtered = _COV.filterCourseDataToChoices(courseData);
  // 同步回 manifest：选择题数量 + 非空章节数
  const courses = filtered.courses || [];
  (window.__COURSE_MANIFEST__ || []).forEach(function(m) {
    const cc = courses.find(function(c) { return c.name === m.name; });
    if (cc) {
      m.question_count = cc.question_count;
      m.chapter_count = (filtered.chapters || []).filter(function(ch) {
        return (ch.course || cc.name) === m.name;
      }).length;
    }
  });
  return filtered;
}
/** URL/本地状态指向已隐藏章节或题型时回退，避免空白页/幽灵选中 */
function sanitizeChoiceOnlySelection() {
  if (!_COV || !CHOICE_ONLY_MODE) return;
  const chRes = _COV.sanitizeSelectedChapter(selectedChapter, currentChapters, true);
  if (chRes.cleared) selectedChapter = '';
  else selectedChapter = chRes.selectedChapter;

  const types = {};
  allQuestions.forEach(q => { types[q.type] = (types[q.type] || 0) + 1; });
  const typeEl = document.getElementById('typeFilter');
  if (typeEl) {
    const tRes = _COV.sanitizeTypeFilter(typeEl.value, types);
    if (tRes.cleared) typeEl.value = '';
    // 动态题型选项：仅可见题型
    refreshTypeFilterOptions(types, typeEl.value);
  }
  if (activeStat && activeStat !== 'all' && activeStat !== 'sub' && activeStat !== 'image') {
    if (!types[activeStat]) activeStat = 'all';
  }
}
function refreshTypeFilterOptions(types, currentValue) {
  const typeEl = document.getElementById('typeFilter');
  if (!typeEl || !_COV) return;
  const items = _COV.buildTypeStatItems(types || {});
  const prev = currentValue != null ? currentValue : typeEl.value;
  typeEl.innerHTML = '';
  const allOpt = document.createElement('option');
  allOpt.value = '';
  allOpt.textContent = items.length <= 1 ? '全部题型' : '全部题型';
  typeEl.appendChild(allOpt);
  items.forEach(function(it) {
    const opt = document.createElement('option');
    opt.value = it.action;
    opt.textContent = it.action;
    typeEl.appendChild(opt);
  });
  // 仅一种题型时也可隐藏下拉噪音：仍保留「全部/该题型」以便筛选语义一致
  if (prev && types[prev]) typeEl.value = prev;
  else typeEl.value = '';
}
// 对 data.js 提供的加载器做包装，使所有使用方拿到的都是选择题数据
if (typeof window.loadCourseData === 'function') {
  const _originalLoadCourseData = window.loadCourseData;
  window.loadCourseData = function(courseName) {
    return _originalLoadCourseData(courseName).then(function(data) {
      return filterCourseDataToChoices(data);
    });
  };
}

// ========================
// Data & State
// ========================
let bank = null;
let allQuestions = [];
let filteredQuestions = [];
let currentPage = 1;
const pageSize = 20;
let currentModalIndex = -1;
let practiceQueue = [];
let practiceIndex = 0;
let selectedChapter = '';
let randomHistory = [];
let lastRandomIdx = -1;
let selectedCourse = '';
let currentChapters = [];
let practiceResults = [];
let practiceFinished = false;
let isLoadingCourse = false;
// 考试模式状态：timed = 限时倒计时秒；target = 目标题数；mixed = 跨科题数；null = 普通练习
let practiceMode = null;
let practiceTimer = null;       // setInterval 句柄
let practiceDeadline = 0;       // 限时模式的截止时间戳
let qualityLedger = null;

function ledgerFromHoldList(hold) {
  const items = {};
  const uids = (hold && Array.isArray(hold.source_uids)) ? hold.source_uids : [];
  for (let i = 0; i < uids.length; i++) {
    const uid = uids[i];
    if (uid) items[uid] = { overall: 'hold' };
  }
  return { items: items };
}

async function loadQualityLedger() {
  if (qualityLedger) return qualityLedger;
  if (window.__QUALITY_LEDGER__) {
    qualityLedger = window.__QUALITY_LEDGER__;
    return qualityLedger;
  }
  // file://：无法 fetch；空 items = 本地预览放行全部题目
  // HTTP(S)：hold 拉取失败 → failClosed，qualityVisible 全 false（生产不得放行）
  try {
    if (window.location.protocol === 'file:') {
      qualityLedger = { items: {} };
    } else {
      const response = await fetch('quality-hold.json');
      if (response.ok) {
        qualityLedger = ledgerFromHoldList(await response.json());
      } else {
        qualityLedger = { items: {}, failClosed: true };
      }
    }
  } catch (e) {
    console.warn('[bank-408] quality hold unavailable; fail-closed', e);
    if (window.location.protocol === 'file:') {
      qualityLedger = { items: {} };
    } else {
      qualityLedger = { items: {}, failClosed: true };
    }
  }
  return qualityLedger;
}

function qualityForQuestion(q) {
  const uid = platformSourceUid(q);
  return qualityLedger && uid ? ((qualityLedger.items || {})[uid] || null) : null;
}

function qualityVisible(q) {
  if (qualityLedger && qualityLedger.failClosed) return false;
  const item = qualityForQuestion(q);
  if (!item) return true;
  if (item.overall === 'hold') return false;
  const course = (qualityLedger.courses || {})[item.course_key];
  return !(course && course.mode === 'strict' && item.overall !== 'certified');
}

function qualityBadgeHtml(q) {
  const item = qualityForQuestion(q);
  if (!item) return '';
  const badges = [];
  if (item.source_fidelity === 'verified') badges.push('<span class="quality-badge quality-source">原书已核对</span>');
  if (item.answer_validation === 'verified') badges.push('<span class="quality-badge quality-answer">答案已验算</span>');
  if (item.overall === 'pending') badges.push('<span class="quality-badge quality-pending">待核验</span>');
  if (item.overall === 'hold') badges.push('<span class="quality-badge quality-hold">质量隔离</span>');
  return badges.join(' ');
}

async function loadBankData(courseName) {
  if (isLoadingCourse) return;
  isLoadingCourse = true;
  const resultText = document.getElementById('resultText');
  try {
    if (!window.loadCourseData) throw new Error('data.js loader not found');
    if (resultText) resultText.innerHTML = '正在加载课程数据…';
    bank = await window.loadCourseData(courseName);
  } catch (e) {
    console.error(e);
    if (resultText) {
      resultText.innerHTML = '课程数据加载失败：' + escapeHtml(e.message) +
        ' <a href="#" onclick="retryLoadCourse();return false;" style="color:var(--accent)">重试</a>';
    }
    bank = null;
  } finally {
    isLoadingCourse = false;
  }
}

function retryLoadCourse() {
  const course = getCurrentCourse();
  if (course) loadBankData(course);
}

// statusMap[key] 新格式：{ mastery?: 'mastered'|'familiar'|'unknown', favorite?: true }
// 旧格式字符串 'favorite'|'mastered'|... 在 loadStatus 时迁移
const STATUS_KEY = 'mathbank_status_v1';
let statusMap = {};

const MASTERY_STATUSES = [
  { key: 'mastered', label: '已掌握', cls: 'mastered' },
  { key: 'familiar', label: '不熟', cls: 'familiar' },
  { key: 'unknown', label: '不会', cls: 'unknown' }
];
const MASTERY_KEYS = new Set(MASTERY_STATUSES.map(m => m.key));

// 详情弹窗：支持打开不在当前筛选列表中的题
let currentModalQuestion = null;

function questionKey(q) { return q.chapter + '::' + q.id; }
function displayId(q) { return (q.id || '').replace(/^[XA]/, ''); }

const OCR_CODE_LINE_RE = /\b(?:void|int|char|float|double|for|while|if|else|return|printf|scanf|typedef|struct)\b|[{};]|\+\+|--/;
const OCR_STRUCTURAL_START_RE = /^(?:[①-⑳]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.．、]?|(?:I{1,3}|IV|VI{0,3}|IX)[.．、]|[（(]?\d+[)）.．、]|[A-D][.．、]|题目图片：|答案图片：|解析图片：)/;
const OCR_ASSET_CAPTION_RE = /^(?:题目图片|答案图片|解析图片|题图|答图)\s*[：:]/;
const OCR_TABLE_HINT_RE = /(?:如下表|下表|表所示|如下图|下图|图所示)/;

function looksLikeOcrCodeLine(line) {
  return OCR_CODE_LINE_RE.test(String(line || ''));
}

function isOcrStructuralBreak(lines, index, hasTableOrFigure) {
  const left = String(lines[index] || '').trim();
  const right = String(lines[index + 1] || '').trim();
  if (!left || !right) return true;
  if (looksLikeOcrCodeLine(left) || looksLikeOcrCodeLine(right)) return true;
  if (OCR_ASSET_CAPTION_RE.test(left) || OCR_ASSET_CAPTION_RE.test(right)) return true;
  if (OCR_STRUCTURAL_START_RE.test(right)) return true;
  if (/^(?:\||表头|指令类型|项目|名称|地址|序号|时间|操作)/.test(right)) return true;
  if (left.endsWith('：') || left.endsWith(':')) return true;
  // 题干明确引出图表时，保留后续短行，避免把表格/拓扑图拼成一段。
  if (hasTableOrFigure && (OCR_TABLE_HINT_RE.test(left) || left.length < 18 || right.length < 18)) return true;
  // OCR 纸面换行通常发生在一行已经接近版心宽度之后；短行换行更可能是结构换行。
  return left.length < 18;
}

function joinOcrWrappedLines(left, right) {
  const a = String(left || '').trimEnd();
  const b = String(right || '').trimStart();
  if (!a) return b;
  if (!b) return a;
  // 英文/数字跨行时补一个词间空格；中文及中英混排不额外插空格。
  if (/[A-Za-z0-9]$/.test(a) && /^[A-Za-z0-9]/.test(b) && !a.endsWith('-')) return a + ' ' + b;
  return a + b;
}

function reflowOcrSoftWraps(text) {
  const normalized = String(text || '').replace(/\r\n?/g, '\n');
  if (!normalized.includes('\n')) return normalized;
  const lines = normalized.split('\n');
  const hasTableOrFigure = OCR_TABLE_HINT_RE.test(normalized);
  const out = [lines[0]];
  for (let index = 0; index < lines.length - 1; index += 1) {
    const next = lines[index + 1];
    if (isOcrStructuralBreak(lines, index, hasTableOrFigure)) out.push(next);
    else out[out.length - 1] = joinOcrWrappedLines(out[out.length - 1], next);
  }
  return out.join('\n');
}

function splitRomanItems(text) {
  return String(text || '')
    .replace(/[\u2028\u2029]/g, '\n')
    .replace(/(?<=\S)[ \t]+(?=(?:I{1,3}|IV)\. )/g, '\n')
    .replace(/\n+(?=(?:I{1,3}|IV)\. )/g, '\n');
}

function normalizeDisplayText(text) {
  if (!text) return text;
  text = reflowOcrSoftWraps(text);
  text = splitRomanItems(text);
  // 修复 OCR 导致的括号左右不一致：如 （) 或 (） 统一为 （）
  return text.replace(/（\s*\)/g, '（）').replace(/\(\s*）/g, '（）');
}

/** 单反斜杠，避免源码里 \\\\ 被二次转义成 KaTeX 换行 */
const TEX_BS = '\u005c';

/** Big-O / log / 根号等复杂度记号 → KaTeX 可识别的 $...$ */
function complexityInnerToLatex(inner) {
  let s = String(inner || '').trim();
  s = s.replace(/²/g, '^{2}').replace(/³/g, '^{3}').replace(/¹/g, '^{1}');
  s = s.replace(/√\s*\{?\s*([A-Za-z0-9]+)\s*\}?/g, TEX_BS + 'sqrt{$1}');
  s = s.replace(/√/g, TEX_BS + 'sqrt{}');
  // nlog2n / log2n（先长后短）→ n\log_2 n；勿二次匹配已转义的 \log
  if (!s.includes(TEX_BS + 'log')) {
    s = s.replace(/n\s*log\s*_?\s*2\s*n/gi, 'n' + TEX_BS + 'log_2 n');
    s = s.replace(/nlog2n/gi, 'n' + TEX_BS + 'log_2 n');
    s = s.replace(/(?<![A-Za-z\\])log\s*_?\s*2\s*n/gi, TEX_BS + 'log_2 n');
    s = s.replace(/(?<![A-Za-z\\])log2n/gi, TEX_BS + 'log_2 n');
  }
  // n^{1/3} 已是 LaTeX；n1/3 / nl/3 容错
  s = s.replace(/\bn\s*\{\s*1\s*\/\s*3\s*\}/g, 'n^{1/3}');
  s = s.replace(/\bn\s*1\s*\/\s*3\b/g, 'n^{1/3}');
  s = s.replace(/\bn\s*l\s*\/\s*3\b/gi, 'n^{1/3}');
  s = s.replace(/\bn\s*1\s*\/\s*2\b/g, 'n^{1/2}');
  s = s.replace(/\bn\^2\b/g, 'n^{2}');
  s = s.replace(/\bn\^3\b/g, 'n^{3}');
  return s;
}

/**
 * 选项/解析里的复杂度、上标等：包进 $...$，供 renderKatex 渲染。
 * 已有 $ 或 \\( 的文本只处理定界符外片段，避免二次包裹。
 */
function prepareMathText(text) {
  let t = normalizeDisplayText(text);
  if (!t) return t;

  // ¹²³ 只在 O(...) 内层转成 ^{}（complexityInnerToLatex）。
  // 这里若全局替换，解析里 3ⁱ⁻¹ 会变成裸 ^{1}，KaTeX 吃不到。

  // 先包 O(...)，内层一次性转成 LaTeX（勿再对 $...$ 内部做 n^{} 替换）
  if (!/\$|\\\(|\\\[/.test(t)) {
    t = t.replace(/\b([Oo])\s*\(\s*([^)]+?)\s*\)/g, (_, letter, inner) => {
      return '$' + letter + '(' + complexityInnerToLatex(inner) + ')$';
    });
  }

  // 仅处理 $...$ 之外的片段
  const parts = t.split(/(\$[^$]*\$)/);
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) continue; // 已在数学定界符内
    let s = parts[i];
    if (!s) continue;
    s = s.replace(/\bnlog2n\b/gi, '$n' + TEX_BS + 'log_2 n$');
    s = s.replace(/\blog2n\b/gi, '$' + TEX_BS + 'log_2 n$');
    s = s.replace(/1og\s*2/gi, 'log2');
    s = s.replace(/(?<![\\$])log\s*2\s*\(\s*([^)]+?)\s*\)/gi, (_, inner) => '$' + TEX_BS + 'log_2(' + inner + ')$');
    s = s.replace(/(?<![\\$])log\s*2\s*(\d+[A-Za-z]?)/gi, (_, n) => '$' + TEX_BS + 'log_2 ' + n + '$');
    s = s.replace(/(?<![\\$])log\s*2\s*([Vv])/g, (_, v) => '$' + TEX_BS + 'log_2 ' + v + '$');
    // 先字面量 n^{2} 后 Unicode ²：顺序反过来会让 n² → $n^{2}$ 再被 \bn\^\{2\} 二次包裹成 $$...$$（块级居中）
    s = s.replace(/\bn\^\{2\}/g, '$n^{2}$');
    s = s.replace(/\bn\^\{3\}/g, '$n^{3}$');
    s = s.replace(/n²/g, '$n^{2}$');
    s = s.replace(/n³/g, '$n^{3}$');
    s = s.replace(/\bn\^\{1\/3\}/g, '$n^{1/3}$');
    s = s.replace(/\bn\^\{1\/2\}/g, '$n^{1/2}$');
    s = s.replace(/(?<![$\w\\])(\d+)\^\{([^}]+)\}/g, (_, a, b) => '$' + a + '^{' + b + '}$');
    s = s.replace(/(?<![$\w\\])(\d+)\^([A-Za-z])(-1)?/g, (_, a, b, c) => '$' + a + '^' + b + (c || '') + '$');
    s = s.replace(/√\s*([A-Za-z0-9]+)/g, '$' + TEX_BS + 'sqrt{$1}$');
    parts[i] = s;
  }
  return parts.join('');
}

/** 笔记预览：复用题干预处理，并把裸 log_{2} / log_2 收成 \log，供 renderKatex 吃掉。 */
function prepareNoteMath(text) {
  let t = prepareMathText(text);
  if (!t) return t;
  return t.replace(/(?<![\\A-Za-z$])log\s*(?=_|\{)/g, TEX_BS + 'log');
}

// ========================
// 笔记图片：粘贴/插入 → 压缩为 dataURL 内联 ![](...)，仅本浏览器保存
// ========================

/** 图片等比压缩到最长边 1200px、JPEG q0.8（canvas 输出 dataURL 不含 ) 与空白，可安全内联 markdown）。 */
function processNoteImage(file) {
  return new Promise((resolve, reject) => {
    if (!file || !file.type || !file.type.startsWith('image/')) {
      reject(new Error('不是图片文件'));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const MAX = 1200;
        let w = img.width, h = img.height;
        if (!w || !h) { reject(new Error('图片解码失败')); return; }
        if (Math.max(w, h) > MAX) {
          const scale = MAX / Math.max(w, h);
          w = Math.round(w * scale);
          h = Math.round(h * scale);
        }
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL('image/jpeg', 0.8));
      };
      img.onerror = () => reject(new Error('图片解码失败'));
      img.src = reader.result;
    };
    reader.onerror = () => reject(new Error('图片读取失败'));
    reader.readAsDataURL(file);
  });
}

/** 在光标处插入片段（图片 markdown 独占一行），并触发 input 走防抖保存。 */
function insertTextAtCursor(ta, snippet) {
  const start = ta.selectionStart != null ? ta.selectionStart : ta.value.length;
  const end = ta.selectionEnd != null ? ta.selectionEnd : start;
  const before = ta.value.slice(0, start);
  const after = ta.value.slice(end);
  const lead = before && !before.endsWith('\n') ? '\n' : '';
  const tail = after && !after.startsWith('\n') ? '\n' : '';
  ta.value = before + lead + snippet + tail + after;
  const pos = (before + lead + snippet).length;
  ta.setSelectionRange(pos, pos);
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

// 图片在笔记文本里只存短占位符 `![图片](noteimg:xxx)`，本体在 noteImagesMap；兼容识别旧的 data: 内联图
const NOTE_IMG_RE = /!\[([^\]]*)\]\((noteimg:[A-Za-z0-9]+|data:image\/(?:png|jpeg);base64,[^)\s]+)\)/g;

function storeNoteImage(dataUrl) {
  const token = 'noteimg:' + Date.now().toString(36) + Math.floor(Math.random() * 1e6).toString(36);
  noteImagesMap[token] = dataUrl;
  if (!saveNoteImages()) {
    // 存储失败：回滚并返回 null，调用方退回内联 base64，绝不静默丢图
    delete noteImagesMap[token];
    return null;
  }
  return token;
}

function resolveNoteImage(ref) {
  if (ref.indexOf('noteimg:') === 0) return noteImagesMap[ref] || null;
  return ref.indexOf('data:image/') === 0 ? ref : null;
}

/** 同步/导出用：把图片占位符替换为（图片），避免大 base64 进平台或剪贴板 */
function stripNoteImages(text) {
  return String(text == null ? '' : text)
    .replace(/!\[([^\]]*)\]\((?:noteimg:[A-Za-z0-9]+|data:image\/[^)]+)\)/g, '（图片）');
}

/** 旧版笔记把 base64 直接内联在文本里：搬到图片 map 并换成短占位符（幂等，只跑一次有改动才存）。
 *  存不下就保留内联形态，不丢图。 */
function migrateLegacyNoteImages() {
  let changed = false;
  Object.keys(notesMap).forEach((key) => {
    const text = notesMap[key];
    if (typeof text !== 'string' || text.indexOf('data:image/') === -1) return;
    notesMap[key] = text.replace(/!\[([^\]]*)\]\(data:image\/(?:png|jpeg);base64,[^)\s]+\)/g, (m, alt, ref) => {
      const token = storeNoteImage(ref);
      if (!token) return m;
      changed = true;
      return `![${alt}](${token})`;
    });
  });
  if (changed) saveNotes();
}

/** 删除笔记时回收不再被任何笔记引用的图片。
 *  从盘上重新读笔记/图片再合并内存，避免旧标签页凭过期内存把别的标签页刚存的图回收掉。 */
function gcNoteImages() {
  const freshNotes = loadSharded(NOTES_KEY);
  const referenced = new Set();
  Object.values(freshNotes).forEach((text) => {
    if (typeof text !== 'string') return;
    let m;
    const re = /!\[([^\]]*)\]\((noteimg:[A-Za-z0-9]+)\)/g;
    while ((m = re.exec(text)) !== null) referenced.add(m[2]);
  });
  noteImagesMap = Object.assign({}, readNoteImagesFresh(), noteImagesMap);
  let changed = false;
  Object.keys(noteImagesMap).forEach((token) => {
    if (!referenced.has(token)) { delete noteImagesMap[token]; changed = true; }
  });
  if (changed) saveNoteImages();
}

function appendNoteTextSegment(el, segment) {
  if (!segment) return;
  const lines = segment.split('\n');
  const isSep = (s) => s.includes('-') && /^\s*\|?[\s\-:|]+\|?\s*$/.test(s);
  const flushText = (arr) => {
    if (!arr.length) return;
    const span = document.createElement('span');
    span.textContent = prepareNoteMath(arr.join('\n'));
    renderKatex(span);
    el.appendChild(span);
  };
  const buildNoteTable = (rows) => {
    const cells = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((s) => s.trim());
    const table = document.createElement('table');
    table.className = 'note-table';
    const headTr = document.createElement('tr');
    cells(rows[0]).forEach((c) => {
      const th = document.createElement('th');
      th.textContent = c;
      renderKatex(th);
      headTr.appendChild(th);
    });
    const thead = document.createElement('thead');
    thead.appendChild(headTr);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    rows.slice(1).forEach((r) => {
      const tr = document.createElement('tr');
      cells(r).forEach((c) => {
        const td = document.createElement('td');
        td.textContent = c;
        renderKatex(td);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  };
  let buf = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].includes('|') && i + 1 < lines.length && isSep(lines[i + 1])) {
      flushText(buf);
      buf = [];
      const rows = [lines[i]];
      i += 2; // 跳过分隔行
      while (i < lines.length && lines[i].includes('|')) { rows.push(lines[i]); i++; }
      el.appendChild(buildNoteTable(rows));
    } else {
      buf.push(lines[i]);
      i++;
    }
  }
  flushText(buf);
}

/** 笔记预览：图片渲染为 <img>，文本段转义后走 KaTeX；数学公式跨图片的边界情况不渲染（可接受）。 */
function renderNotePreview(el, text) {
  el.innerHTML = '';
  let last = 0;
  let m;
  while ((m = NOTE_IMG_RE.exec(text)) !== null) {
    if (m.index > last) appendNoteTextSegment(el, text.slice(last, m.index));
    const dataUrl = resolveNoteImage(m[2]);
    if (dataUrl) {
      const img = document.createElement('img');
      img.className = 'note-img';
      img.alt = m[1] || '笔记图片';
      img.src = dataUrl;
      el.appendChild(img);
    } else {
      const missing = document.createElement('span');
      missing.className = 'note-img-missing';
      missing.textContent = '（图片缺失）';
      el.appendChild(missing);
    }
    last = NOTE_IMG_RE.lastIndex;
  }
  NOTE_IMG_RE.lastIndex = 0;
  if (last < text.length) appendNoteTextSegment(el, text.slice(last));
}

/** 平台挂载 + 已登录：把图片送视觉模型复现为 Markdown（表格→Markdown 表格）。
 *  返回 Promise：{ok:true, markdown} 或 {ok:false, status}
 *  （status: not_platform / not_logged_in / HTTP 状态码 / error / empty）。 */
function convertNoteImageDataUrl(dataUrl) {
  if (!window.ViewerPlatformSync || !ViewerPlatformSync.onPlatformHost || !ViewerPlatformSync.onPlatformHost()) {
    return Promise.resolve({ ok: false, status: 'not_platform' });
  }
  var sync = window.ViewerPlatformSync;
  var authP = sync.ensureAuth ? sync.ensureAuth() : Promise.resolve(null);
  return authP.then(function (auth) {
    if (auth && auth.ok === false) return { ok: false, status: 'not_logged_in' };
    var headers = {};
    if (auth && auth.token) headers.Authorization = 'Bearer ' + auth.token;
    return fetch(dataUrl)
      .then(function (r) { return r.blob(); })
      .then(function (blob) {
        var form = new FormData();
        form.append('image', blob, 'note.jpg');
        return fetch('/api/notes/image-to-markdown', { method: 'POST', credentials: 'include', headers: headers, body: form });
      })
      .then(function (res) {
        if (!res.ok) return { ok: false, status: res.status };
        return res.json().then(function (data) {
          var md = ((data && data.markdown) || '').trim();
          return md ? { ok: true, markdown: md } : { ok: false, status: 'empty' };
        });
      });
  }).catch(function () { return { ok: false, status: 'error' }; });
}

let _noteConvertNotPlatformToasted = false;
/** 转文字失败的分级提示；图片本体已保存，不影响笔记。not_platform 每次会话只提示一次。 */
function noteImageConvertFailToast(status) {
  if (status === 'not_platform') {
    if (_noteConvertNotPlatformToasted) return;
    _noteConvertNotPlatformToasted = true;
    flashToast('图片已保存；转文字需从学习平台打开题库');
    return;
  }
  var msg = {
    not_logged_in: '图片已保存；转文字需先登录学习平台',
    empty: '图片已保存；转文字结果为空，可重试',
    error: '图片已保存；转文字失败，可稍后重试',
  }[status];
  if (!msg) {
    if (status === 403) msg = '图片已保存；转文字仅管理员可用';
    else if (status === 503) msg = '图片已保存；服务端未开启图片转文字';
    else if (status === 429) msg = '图片已保存；转文字限流，请稍后重试';
    else msg = '图片已保存；转文字失败（' + status + '），可稍后重试';
  }
  flashToast(msg);
}

/** 插入图片后的增值路径：成功追加 Markdown 供校对；失败按原因提示（不再静默，方便定位前提缺失）。 */
function maybeConvertNoteImage(ta, dataUrl) {
  convertNoteImageDataUrl(dataUrl).then(function (r) {
    if (r.ok) {
      insertTextAtCursor(ta, r.markdown);
      flashToast('图片已转为文字，请校对');
    } else {
      noteImageConvertFailToast(r.status);
    }
  });
}

/** 「📝 图中文字」按钮：对笔记里已存在的图片补转文字，成功后追加到光标处，图片占位符保留。 */
function convertFirstNoteImage(ta) {
  var m = /!\[[^\]]*\]\((noteimg:[A-Za-z0-9]+)\)/.exec(ta.value || '');
  if (!m) { flashToast('笔记里没有可转换的图片'); return; }
  var dataUrl = resolveNoteImage(m[1]);
  if (!dataUrl) { flashToast('图片本体缺失，无法转换'); return; }
  flashToast('正在转换图片文字…');
  convertNoteImageDataUrl(dataUrl).then(function (r) {
    if (r.ok) {
      insertTextAtCursor(ta, '\n' + r.markdown);
      flashToast('图片已转为文字，请校对');
    } else {
      noteImageConvertFailToast(r.status);
    }
  });
}

function getTotalPages() { return Math.ceil(filteredQuestions.length / pageSize) || 1; }

function shuffleArray(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function debounce(fn, ms) {
  let timer;
  return function(...args) { clearTimeout(timer); timer = setTimeout(() => fn.apply(this, args), ms); };
}

function resetAndFilter() { currentPage = 1; applyFilters(); }

function resetAllFilters() {
  document.getElementById('searchInput').value = '';
  document.getElementById('typeFilter').value = '';
  document.getElementById('featureFilter').value = '';
  document.getElementById('sortSelect').value = 'default';
  selectedChapter = '';
  activeStat = 'all';
  activeStatusFilter = '';
  renderChapters();
  resetAndFilter();
}

function toggleViewMode() {
  viewMode = viewMode === 'compact' ? 'default' : 'compact';
  localStorage.setItem(VIEW_KEY, viewMode);
  document.body.classList.toggle('compact-view', viewMode === 'compact');
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  renderGrid(search);
}

function openModal(id) {
  document.getElementById(id).classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModalById(id) {
  document.getElementById(id).classList.remove('active');
  document.body.style.overflow = '';
}

function getAvailableCourses() {
  // 优先 manifest：单科 data-*.json 的 courses 只有当前科，不能用来画四科标签
  if (window.__COURSE_MANIFEST__ && window.__COURSE_MANIFEST__.length) {
    return window.__COURSE_MANIFEST__.map(c => ({
      name: c.name,
      short: c.short,
      question_count: c.question_count,
    }));
  }
  if (bank && bank.courses) return bank.courses;
  return [];
}

function getCurrentCourse() {
  const list = getAvailableCourses();
  if (!selectedCourse && list.length) selectedCourse = list[0].name;
  return selectedCourse;
}

function getCurrentChapters() {
  if (!bank) return [];
  const course = getCurrentCourse();
  return bank.chapters.filter(ch => (ch.course || (bank.courses && bank.courses[0] ? bank.courses[0].name : '')) === course);
}

// ========================
// Status (favorite / mastery) & Practice result & Spaced Repetition
// ========================
const PRACTICE_KEY = 'mathbank_practice_v1';
let practiceMap = {};

// 间隔重复：每题记录「上次做答时间 / 答对累计次数 / 下次复习时间」
// 间隔阶梯：第 1/2/3/4/N 次答对 → 1 / 3 / 7 / 14 / 30 天；答错 → 重置为 1 天
const REVIEW_KEY = 'mathbank_review_v1';
let reviewMap = {};
const REVIEW_INTERVALS = [1, 3, 7, 14, 30];
const MS_PER_DAY = 86400000;

// 个人笔记：按题目 key 存到 localStorage
const NOTES_KEY = 'mathbank_notes_v1';
let notesMap = {};
// 笔记图片本体：token → dataURL，笔记文本里只存 `![图片](noteimg:xxx)` 短占位符
const NOTE_IMAGES_KEY = 'mathbank_note_imgs_v1';
let noteImagesMap = {};

// 题目纠错反馈：按题目 key 累积 issue 字符串数组
const ISSUES_KEY = 'mathbank_issues_v1';
let issuesMap = {};
const ISSUE_QUEUE_KEY = 'mathbank_issue_queue_v1';
let issueQueue = [];

// 错题日志：每次答错追加一条
const WRONG_LOG_KEY = 'mathbank_wrong_log_v1';
let wrongLog = [];  // 数组：{key, at, chapter, qid, type, page, userAnswer?, correctAnswer?}

// 答题历史：每次答题追加（用于"今日做题数"等统计更准确）
const ATTEMPT_LOG_KEY = 'mathbank_attempt_log_v1';
let attemptLog = [];  // 数组：{key, at, isCorrect, course}

// 搜索历史：最近 10 次搜索词
const SEARCH_HISTORY_KEY = 'mathbank_search_history_v1';
const SEARCH_HISTORY_MAX = 10;
let searchHistory = [];

// 列表视图模式：default | compact
const VIEW_KEY = 'mathbank_view_v1';
let viewMode = 'default';

function safeSetItem(key, value) {
  if (window.ViewerStorage && ViewerStorage.safeSetItem) {
    const ok = ViewerStorage.safeSetItem(key, value);
    if (!ok && typeof flashToast === 'function') {
      flashToast('本地存储空间不足，请导出备份后清理');
    }
    return ok;
  }
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (e) {
    if (typeof flashToast === 'function') {
      flashToast('本地存储空间不足，请导出备份后清理');
    }
    return false;
  }
}

// 分片 map 读取：loadShardedMap 自带旧单 key 兼容（无 __meta 时读 baseKey）
function loadSharded(baseKey) {
  if (window.ViewerStorage && ViewerStorage.loadShardedMap) {
    return ViewerStorage.loadShardedMap(baseKey) || {};
  }
  try {
    const raw = localStorage.getItem(baseKey);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

// 分片 map 写入：大对象拆 key，saveShardedMap 写成功后会清掉旧单 key
function saveSharded(baseKey, map) {
  if (window.ViewerStorage && ViewerStorage.saveShardedMap) {
    return ViewerStorage.saveShardedMap(baseKey, map);
  }
  return safeSetItem(baseKey, JSON.stringify(map || {}));
}

function normalizeStatusEntry(val) {
  // 新格式
  if (val && typeof val === 'object' && !Array.isArray(val)) {
    return {
      mastery: MASTERY_KEYS.has(val.mastery) ? val.mastery : '',
      favorite: !!val.favorite
    };
  }
  // 旧格式：单一字符串
  if (val === 'favorite') return { mastery: '', favorite: true };
  if (MASTERY_KEYS.has(val)) return { mastery: val, favorite: false };
  return { mastery: '', favorite: false };
}

function getStatusEntry(qOrKey) {
  const key = typeof qOrKey === 'string' ? qOrKey : questionKey(qOrKey);
  const raw = statusMap[key];
  if (!raw) return { mastery: '', favorite: false };
  return normalizeStatusEntry(raw);
}

function writeStatusEntry(key, entry) {
  if (!entry.mastery && !entry.favorite) delete statusMap[key];
  else statusMap[key] = { mastery: entry.mastery || '', favorite: !!entry.favorite };
}

function loadStatus() {
  try {
    statusMap = loadSharded(STATUS_KEY);
    const praw = localStorage.getItem(PRACTICE_KEY);
    practiceMap = praw ? JSON.parse(praw) : {};
    const rraw = localStorage.getItem(REVIEW_KEY);
    reviewMap = rraw ? JSON.parse(rraw) : {};
    notesMap = loadSharded(NOTES_KEY);
    noteImagesMap = loadSharded(NOTE_IMAGES_KEY);
    migrateLegacyNoteImages();
    const iraw = localStorage.getItem(ISSUES_KEY);
    issuesMap = iraw ? JSON.parse(iraw) : {};
    const qraw = localStorage.getItem(ISSUE_QUEUE_KEY);
    issueQueue = qraw ? JSON.parse(qraw) : [];
    const wraw = localStorage.getItem(WRONG_LOG_KEY);
    wrongLog = wraw ? JSON.parse(wraw) : [];
    const arraw = localStorage.getItem(ATTEMPT_LOG_KEY);
    attemptLog = arraw ? JSON.parse(arraw) : [];
    const shraw = localStorage.getItem(SEARCH_HISTORY_KEY);
    searchHistory = shraw ? JSON.parse(shraw) : [];
    viewMode = localStorage.getItem(VIEW_KEY) || 'default';
    if (viewMode === 'compact') document.body.classList.add('compact-view');
    // 迁移：correct/wrong → practiceMap；字符串 status → {mastery, favorite}
    let migrated = false;
    Object.entries(statusMap).forEach(([key, val]) => {
      if (val === 'correct' || val === 'wrong') {
        practiceMap[key] = val;
        delete statusMap[key];
        migrated = true;
        return;
      }
      if (typeof val === 'string') {
        const entry = normalizeStatusEntry(val);
        writeStatusEntry(key, entry);
        migrated = true;
      } else if (val && typeof val === 'object') {
        // 规范化字段
        const entry = normalizeStatusEntry(val);
        if (!entry.mastery && !entry.favorite) {
          delete statusMap[key];
          migrated = true;
        } else if (val.mastery !== entry.mastery || !!val.favorite !== entry.favorite || Object.keys(val).some(k => k !== 'mastery' && k !== 'favorite')) {
          writeStatusEntry(key, entry);
          migrated = true;
        }
      }
    });
    if (migrated) {
      saveStatus();
      savePractice();
    }
  } catch (e) {
    statusMap = {};
    practiceMap = {};
    reviewMap = {};
    notesMap = {};
    issuesMap = {};
    issueQueue = [];
    wrongLog = [];
    attemptLog = [];
  }
}

function saveStatus() {
  saveSharded(STATUS_KEY, statusMap);
}

function savePractice() {
  safeSetItem(PRACTICE_KEY, JSON.stringify(practiceMap));
}

function saveReview() {
  safeSetItem(REVIEW_KEY, JSON.stringify(reviewMap));
}

function saveNotes() {
  safeSetItem(NOTES_KEY, JSON.stringify(notesMap));
}
function saveNoteImages() {
  return saveSharded(NOTE_IMAGES_KEY, noteImagesMap);
}

function readNoteImagesFresh() {
  return loadSharded(NOTE_IMAGES_KEY);
}
function saveIssues() {
  safeSetItem(ISSUES_KEY, JSON.stringify(issuesMap));
}
function saveIssueQueue() {
  safeSetItem(ISSUE_QUEUE_KEY, JSON.stringify(issueQueue || []));
}

function saveSearchHistory() {
  safeSetItem(SEARCH_HISTORY_KEY, JSON.stringify(searchHistory));
}
function pushSearchHistory(term) {
  if (!term) return;
  // 去重，最新的放最前
  searchHistory = [term, ...searchHistory.filter(t => t !== term)].slice(0, SEARCH_HISTORY_MAX);
  saveSearchHistory();
  renderSearchHistoryDropdown();
}
function renderSearchHistoryDropdown() {
  const dd = document.getElementById('searchHistoryDropdown');
  if (!dd) return;
  if (!searchHistory.length) { dd.hidden = true; dd.innerHTML = ''; return; }
  dd.hidden = false;
  dd.innerHTML = `
    <div class="search-history-head">
      <span>最近搜索</span>
      <button type="button" class="search-history-clear" id="searchHistoryClear">清空</button>
    </div>
    ${searchHistory.map(t => `<div class="search-history-item" data-term="${escapeHtml(t)}">${escapeHtml(t)}</div>`).join('')}
  `;
  dd.querySelectorAll('.search-history-item').forEach(el => {
    el.onclick = () => {
      const inp = document.getElementById('searchInput');
      inp.value = el.dataset.term;
      dd.hidden = true;
      resetAndFilter();
    };
  });
  const clr = document.getElementById('searchHistoryClear');
  if (clr) clr.onclick = (e) => {
    e.stopPropagation();
    searchHistory = [];
    saveSearchHistory();
    renderSearchHistoryDropdown();
  };
}
function getNote(q) { return notesMap[questionKey(q)] || ''; }
function setNote(q, text) {
  const key = questionKey(q);
  if (text) notesMap[key] = text; else delete notesMap[key];
  saveNotes();
  if (!text) gcNoteImages();
}

function textNotePayload(q, markdown) {
  // 平台文本笔记限 20000 字符，图片只存本浏览器：同步时替换为占位
  const md = stripNoteImages(markdown).trim();
  if (!md) return null;
  return {
    bank: platformBankCode(q),
    source_uid: platformSourceUid(q),
    chapter: q.chapter || '',
    title: String(q.content || '').slice(0, 2000),
    markdown: md.slice(0, 20000),
  };
}

function flushLocalTextNotes() {
  const api = window.ViewerQuestionNotes;
  if (!api || !api.importTextNotes) return;
  if (!window.ViewerPlatformSync || !ViewerPlatformSync.onPlatformHost || !ViewerPlatformSync.onPlatformHost()) return;
  const items = [];
  allQuestions.forEach((q) => {
    const payload = textNotePayload(q, getNote(q));
    if (payload) items.push(payload);
  });
  if (!items.length) return;
  api.importTextNotes(items);
}

function syncOneTextNote(q) {
  const api = window.ViewerQuestionNotes;
  if (!api || !api.importTextNotes) return;
  const payload = textNotePayload(q, getNote(q));
  if (!payload) return;
  api.importTextNotes([payload]);
}

// 取得题目的复习记录；若无记录则返回初始结构
function getReview(q) {
  const key = questionKey(q);
  return reviewMap[key] || { lastSeenAt: null, lastResult: null, streak: 0, nextReviewAt: null, intervalDays: null };
}

// 根据最近答对次数返回间隔天数（按 REVIEW_INTERVALS 取值）
function streakToInterval(streak) {
  const idx = Math.max(0, Math.min(streak, REVIEW_INTERVALS.length) - 1);
  return REVIEW_INTERVALS[idx === -1 ? 0 : idx];
}

// 答对 / 答错后更新该题的复习计划
function updateReviewSchedule(q, isCorrect, now) {
  const key = questionKey(q);
  const ts = now || Date.now();
  const prev = getReview(q);
  let streak, intervalDays;
  if (isCorrect) {
    streak = (prev.streak || 0) + 1;
    intervalDays = streakToInterval(streak);
  } else {
    // 答错：重置为第 1 次（明天再练）
    streak = 0;
    intervalDays = 1;
  }
  reviewMap[key] = {
    lastSeenAt: ts,
    lastResult: isCorrect ? 'correct' : 'wrong',
    streak,
    nextReviewAt: ts + intervalDays * MS_PER_DAY,
    intervalDays
  };
  saveReview();
}

// 列出已到期（nextReviewAt <= now）的题目；遵循当前选中课程 + 章节过滤
function getDueQuestions(now) {
  const ts = now || Date.now();
  const out = [];
  for (const q of allQuestions) {
    const r = reviewMap[questionKey(q)];
    if (!r || !r.nextReviewAt) continue;
    if (r.nextReviewAt <= ts) out.push(q);
  }
  return out;
}

// 当前已到期题目数（用于侧栏徽章）
function dueCount(now) {
  return getDueQuestions(now).length;
}

// 刷新侧栏今日复习徽章
function refreshDueBadge() {
  const badge = document.getElementById('dueBadge');
  const btn = document.getElementById('btnDueReview');
  if (!badge || !btn) return;
  const n = dueCount();
  badge.textContent = n;
  badge.hidden = false;
  badge.classList.toggle('zero', n === 0);
  btn.title = n > 0 ? `今日复习：${n} 道题到期` : '今日复习：暂无到期题';
}

function buildFullExportPayload() {
  return {
    version: 2,
    exportedAt: new Date().toISOString(),
    status: statusMap,
    practice: practiceMap,
    review: reviewMap,
    notes: notesMap,
    noteImages: noteImagesMap,
    issues: issuesMap,
    issueQueue: issueQueue,
    wrongLog: wrongLog,
    attemptLog: attemptLog,
    searchHistory: searchHistory
  };
}

function exportProgress() {
  const data = buildFullExportPayload();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `mathbank-progress-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
  flashToast('已导出完整进度（含笔记/复习/错题）');
}

function applyImportedStatus(rawStatus) {
  if (!rawStatus || typeof rawStatus !== 'object') return;
  const next = {};
  Object.entries(rawStatus).forEach(([key, val]) => {
    if (val === 'correct' || val === 'wrong') {
      practiceMap[key] = val;
      return;
    }
    const entry = normalizeStatusEntry(val);
    if (entry.mastery || entry.favorite) next[key] = entry;
  });
  statusMap = next;
}

function importProgress(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      if (data.status && typeof data.status === 'object') {
        applyImportedStatus(data.status);
        saveStatus();
      }
      if (data.practice && typeof data.practice === 'object') {
        practiceMap = data.practice;
        savePractice();
      }
      // v2 全量字段（备份 / 新导出）
      if (data.review && typeof data.review === 'object') {
        reviewMap = data.review;
        saveReview();
      }
      if (data.notes && typeof data.notes === 'object') {
        notesMap = data.notes;
        saveNotes();
      }
      if (data.noteImages && typeof data.noteImages === 'object') {
        // 合并而非整体覆盖：旧备份里没有图片字段，避免把现有图库清空
        noteImagesMap = Object.assign({}, noteImagesMap, data.noteImages);
        saveNoteImages();
      }
      if (data.issues && typeof data.issues === 'object') {
        issuesMap = data.issues;
        saveIssues();
      }
      if (Array.isArray(data.issueQueue)) {
        issueQueue = data.issueQueue;
        saveIssueQueue();
      }
      if (Array.isArray(data.wrongLog)) {
        wrongLog = data.wrongLog;
        safeSetItem(WRONG_LOG_KEY, JSON.stringify(wrongLog));
      }
      if (Array.isArray(data.attemptLog)) {
        attemptLog = data.attemptLog;
        safeSetItem(ATTEMPT_LOG_KEY, JSON.stringify(attemptLog));
      }
      if (Array.isArray(data.searchHistory)) {
        searchHistory = data.searchHistory.slice(0, SEARCH_HISTORY_MAX);
        saveSearchHistory();
      }
      renderStats();
      refreshChapterMastery();
      refreshDueBadge();
      const search = document.getElementById('searchInput').value.trim().toLowerCase();
      renderGrid(search);
      flashToast(data.version >= 2 ? '完整进度已导入' : '进度已导入（旧版文件，仅含掌握/练习）');
    } catch (err) {
      alert('导入失败：文件格式不正确');
    }
  };
  reader.readAsText(file);
}

/** 兼容旧调用：返回 mastery，若无 mastery 且收藏则 'favorite'（仅用于部分展示） */
function getStatus(q) {
  const e = getStatusEntry(q);
  if (e.mastery) return e.mastery;
  if (e.favorite) return 'favorite';
  return '';
}

function getMastery(q) {
  return getStatusEntry(q).mastery;
}

function isFavorite(q) {
  return getStatusEntry(q).favorite;
}

function getPracticeResult(q) {
  return practiceMap[questionKey(q)] || '';
}

function setMastery(q, status) {
  const key = questionKey(q);
  const entry = getStatusEntry(key);
  // 再次点击同一掌握度 → 清除掌握度（保留收藏）
  if (!status || entry.mastery === status) entry.mastery = '';
  else entry.mastery = status;
  writeStatusEntry(key, entry);
  saveStatus();
  // 手动调整掌握度时同步刷新复习计划
  if (entry.mastery === 'mastered') {
    const ts = Date.now();
    reviewMap[key] = { lastSeenAt: ts, lastResult: null, streak: 1, nextReviewAt: ts + 7 * MS_PER_DAY, intervalDays: 7 };
  } else if (entry.mastery === 'familiar') {
    const ts = Date.now();
    reviewMap[key] = { lastSeenAt: ts, lastResult: null, streak: 0, nextReviewAt: ts + 2 * MS_PER_DAY, intervalDays: 2 };
  } else if (entry.mastery === 'unknown') {
    const ts = Date.now();
    reviewMap[key] = { lastSeenAt: ts, lastResult: 'wrong', streak: 0, nextReviewAt: ts + MS_PER_DAY, intervalDays: 1 };
  } else {
    // 仅清除掌握度时不强制删 review（避免误伤练习产生的计划）；无掌握时若无 nextReview 可保留
  }
  saveReview();
  renderStats();
  renderMarkDashboard();
  refreshChapterMastery();
  refreshDueBadge();
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  renderGrid(search);
  // 从平台打开时：标记后后台静默同步（无 UI）
  if (typeof queueAutoSyncToPlatform === 'function' && entry.mastery) {
    try { localStorage.removeItem('wd408_last_sync_sig'); } catch (e) {}
    queueAutoSyncToPlatform(q);
  }
}

function toggleFavorite(q) {
  const key = questionKey(q);
  const entry = getStatusEntry(key);
  entry.favorite = !entry.favorite;
  writeStatusEntry(key, entry);
  saveStatus();
  renderStats();
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  renderGrid(search);
}

function setPracticeResult(q, isCorrect) {
  const key = questionKey(q);
  practiceMap[key] = isCorrect ? 'correct' : 'wrong';
  savePractice();
  // 写入答题历史
  attemptLog.push({key, at: Date.now(), isCorrect, course: q.course || getCurrentCourse() || ''});
  if (attemptLog.length > 2000) attemptLog = attemptLog.slice(-2000);
  safeSetItem(ATTEMPT_LOG_KEY, JSON.stringify(attemptLog));
  if (!isCorrect) {
    wrongLog.push({
      key,
      at: Date.now(),
      chapter: q.chapter || '',
      qid: q.id || '',
      type: q.type || '',
      page: q.page || 0,
      correctAnswer: q.answer && q.answer.choice
    });
    if (wrongLog.length > 2000) wrongLog = wrongLog.slice(-2000);
    safeSetItem(WRONG_LOG_KEY, JSON.stringify(wrongLog));
  }
}

// ========================
// 继续上次（对齐数学题库：记录章节+题号，顶栏一键继续）
// ========================
let CURSOR_KEY = 'wd408_cursor_default';

function refreshCursorKey() {
  const course = getCurrentCourse() || 'default';
  CURSOR_KEY = 'wd408_cursor_' + course;
}

function loadCursor() {
  try {
    const raw = localStorage.getItem(CURSOR_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function saveCursor(q) {
  if (!q) return;
  const course = q.course || getCurrentCourse() || '';
  const payload = {
    course: course,
    chapter: q.chapter || '',
    chapterKey: q.chapterKey || '',
    questionId: String(q.id || ''),
    type: q.type || '',
    page: q.page || null,
    at: Date.now(),
  };
  try {
    localStorage.setItem(CURSOR_KEY, JSON.stringify(payload));
  } catch (e) {}
  // 供平台/首页「继续上次」读取（与数学 mathbank_last 并列）
  try {
    localStorage.setItem('wd408_last', JSON.stringify({
      key: '408',
      course: course,
      title: '王道 408 · ' + (course || '精选'),
      href: '/banks/408/?course=' + encodeURIComponent(course) + '&resume=1',
      chapter: payload.chapter,
      chapterKey: payload.chapterKey,
      questionId: payload.questionId,
      label: (payload.chapter ? payload.chapter + ' · ' : '') + payload.questionId,
      at: payload.at,
    }));
  } catch (e) {}
  updateResumeBar();
  updateChapterCursorUI();
}

function clearCursor() {
  try { localStorage.removeItem(CURSOR_KEY); } catch (e) {}
  updateResumeBar();
  updateChapterCursorUI();
}

function updateResumeBar() {
  const bar = document.getElementById('resumeBar');
  const textEl = document.getElementById('resumeText');
  if (!bar || !textEl) return;
  const pos = loadCursor();
  if (!pos || !pos.questionId) {
    bar.classList.remove('is-visible');
    bar.hidden = true;
    return;
  }
  const label = (pos.chapter ? pos.chapter + ' · ' : '') + pos.questionId;
  textEl.innerHTML = '上次练到：<strong>' + escapeHtml(label) + '</strong>'
    + (pos.type ? ' <span style="color:var(--text-tertiary)">· ' + escapeHtml(pos.type) + '</span>' : '');
  bar.hidden = false;
  bar.classList.add('is-visible');
}

function updateChapterCursorUI() {
  const cursor = loadCursor();
  document.querySelectorAll('#chapterList .tree-toggle').forEach(el => {
    const key = el.dataset.key || '';
    // 叶子为二级小节：dataset.key = l1|l2|选择题；兼容旧 cursor
    let isCursor = false;
    if (cursor && cursor.chapterKey) {
      if (key === cursor.chapterKey) isCursor = true;
      else if (el.classList.contains('leaf')) {
        isCursor = l2NodeMatchesSelected({
          filterKey: el.dataset.filterKey || key,
          key,
          l2Key: el.dataset.l2Key || '',
        }, cursor.chapterKey);
      }
    }
    el.classList.toggle('has-cursor', isCursor);
    const labelSpan = el.querySelector('span:nth-child(2)') || el.querySelector('span');
    if (!labelSpan) return;
    let dot = el.querySelector('.cursor-dot');
    if (isCursor && !dot) {
      const arrow = el.querySelector('.arrow');
      if (arrow) arrow.insertAdjacentHTML('afterend', '<span class="cursor-dot" title="上次练习章节"></span>');
      else el.insertAdjacentHTML('afterbegin', '<span class="cursor-dot" title="上次练习章节"></span>');
    } else if (!isCursor && dot) {
      dot.remove();
    }
  });
}

function findQuestionByCursor(pos) {
  if (!pos) return null;
  // 优先 chapter + id
  let q = allQuestions.find(x =>
    String(x.id) === String(pos.questionId)
    && (!pos.chapter || x.chapter === pos.chapter)
  );
  if (q) return q;
  // 回退：仅 id（当前课程内）
  q = allQuestions.find(x => String(x.id) === String(pos.questionId));
  return q || null;
}

function resumeLastPosition() {
  const pos = loadCursor();
  if (!pos) {
    flashToast('没有上次练习记录');
    return;
  }
  // 切到对应课程
  if (pos.course && pos.course !== getCurrentCourse()) {
    switchCourse(pos.course).then(() => {
      setTimeout(() => resumeLastPosition(), 50);
    });
    return;
  }
  // 按章节筛选，方便对照侧栏
  if (pos.chapterKey) {
    selectedChapter = pos.chapterKey;
  } else {
    selectedChapter = '';
  }
  document.getElementById('searchInput').value = '';
  document.getElementById('typeFilter').value = '';
  document.getElementById('featureFilter').value = '';
  activeStatusFilter = '';
  activeStat = 'all';
  applyFilters();
  renderChapters();

  let q = findQuestionByCursor(pos);
  let idx = q ? filteredQuestions.indexOf(q) : -1;
  if (idx < 0 && pos.chapterKey) {
    // 章节筛选下找不到则放宽到全部
    selectedChapter = '';
    applyFilters();
    renderChapters();
    q = findQuestionByCursor(pos);
    idx = q ? filteredQuestions.indexOf(q) : -1;
  }
  if (idx < 0 || !q) {
    flashToast('找不到上次的题目，可能数据已更新');
    return;
  }
  currentPage = Math.floor(idx / pageSize) + 1;
  renderGrid(document.getElementById('searchInput').value.trim().toLowerCase());
  renderPagination();
  openDetail(idx);
  flashToast('已继续：' + (pos.chapter ? pos.chapter + ' · ' : '') + pos.questionId);
}

// ========================
// URL state sync
// ========================
function syncUrl() {
  const params = new URLSearchParams();
  const course = getCurrentCourse();
  if (course) params.set('course', course);
  if (selectedChapter) params.set('chapter', selectedChapter);
  const type = document.getElementById('typeFilter').value;
  if (type) params.set('type', type);
  const feature = document.getElementById('featureFilter').value;
  if (feature) params.set('feature', feature);
  const search = document.getElementById('searchInput').value.trim();
  if (search) params.set('search', search);
  if (currentPage > 1) params.set('page', String(currentPage));

  const url = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
  try { history.replaceState(null, '', url); } catch (e) {}
}

function restoreFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const course = params.get('course');
  if (course && getAvailableCourses().some(c => c.name === course)) selectedCourse = course;
  selectedChapter = params.get('chapter') || '';
  document.getElementById('typeFilter').value = params.get('type') || '';
  document.getElementById('featureFilter').value = params.get('feature') || '';
  document.getElementById('searchInput').value = params.get('search') || '';
  currentPage = parseInt(params.get('page'), 10) || 1;
}

// ========================
// Build questions
// ========================
function buildAllQuestions() {
  allQuestions = [];
  const tokenSplitRe = /[\s,.;:!?。，；：！？、（）()\[\]"'"]+/;
  currentChapters.forEach(ch => {
    const chapterKey = (ch.l1_name || '?') + '|' + (ch.l2_name || '?') + '|' + (ch.section_type || '?');
    ch.questions.forEach(q => {
      const entry = {...q, chapter: ch.name, chapterKey: chapterKey, course: ch.course || ''};

      // 为每道题建立可搜索 token 集合，多词搜索时比长字符串 includes 更快且更准
      const tokens = new Set();
      function addTokens(text) {
        if (!text) return;
        text.toLowerCase().split(tokenSplitRe).forEach(t => { if (t.length > 1) tokens.add(t); });
      }
      addTokens(q.content);
      addTokens(ch.name);
      addTokens(q.id);
      if (q.sub_questions) q.sub_questions.forEach(addTokens);
      if (q.options) Object.values(q.options).forEach(addTokens);
      if (q.answer) {
        if (q.answer.choice) addTokens(q.answer.choice);
        if (q.answer.explanation) addTokens(q.answer.explanation);
      }
      entry._searchTokens = tokens;

      // 保留完整搜索文本用于连续子串兜底
      const parts = [q.content, ch.name, q.id];
      if (q.sub_questions) parts.push(...q.sub_questions);
      if (q.options) parts.push(...Object.values(q.options));
      if (q.answer) {
        if (q.answer.choice) parts.push(q.answer.choice);
        if (q.answer.explanation) parts.push(q.answer.explanation);
      }
      entry._searchText = parts.join(' ').toLowerCase();
      allQuestions.push(entry);
    });
  });
}

async function init() {
  loadStatus();
  restoreFromUrl();
  renderCourseTabs();
  renderMobileCourseSelect();

  const course = getCurrentCourse();
  const ledgerPromise = loadQualityLedger();
  if (course) {
    document.getElementById('resultText').textContent = '正在加载课程数据…';
    await Promise.all([ledgerPromise, loadBankData(course)]);
  } else {
    await ledgerPromise;
  }

  currentChapters = getCurrentChapters();
  buildAllQuestions();
  sanitizeChoiceOnlySelection();

  // 过滤后刷新课程标签数量（manifest 已在 filter 中写回选择题数）
  renderCourseTabs();
  renderMobileCourseSelect();
  renderChapters();
  renderStats();
  renderMarkDashboard();
  applyFilters();
  refreshDueBadge();
  setupEvents();
  refreshCursorKey();
  updateResumeBar();
  updateChapterCursorUI();
  setupShellContinue();
  const btnRandInline = document.getElementById('btnRandomInline');
  if (btnRandInline) btnRandInline.addEventListener('click', randomQuestion);

  // 打开、切回页面、重新联网及本地数据变化时自动双向同步。
  if (typeof setupAutomaticPlatformSync === 'function') setupAutomaticPlatformSync();
  setTimeout(flushLocalTextNotes, 900);
  // 主页/链接带 ?resume=1 时自动打开上次题目
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get('resume') === '1' && loadCursor()) {
      setTimeout(() => resumeLastPosition(), 120);
    }
  } catch (e) {}
}

/** 顶栏「继续上次」：本册 / 数学 / 408 统一入口 */
function setupShellContinue() {
  const cont = document.getElementById('shellContinue');
  if (!cont) return;
  const pos = typeof loadCursor === 'function' ? loadCursor() : null;
  let lastMath = null;
  try { lastMath = JSON.parse(localStorage.getItem('mathbank_last') || 'null'); } catch (e) {}
  if (pos && pos.questionId) {
    cont.hidden = false;
    cont.textContent = '继续本册';
    cont.href = '#';
    cont.onclick = (e) => { e.preventDefault(); resumeLastPosition(); };
  } else if (lastMath && lastMath.href) {
    cont.hidden = false;
    cont.textContent = '继续数学';
    // mathbank_last.href 常为相对路径，平台下改绝对
    let href = lastMath.href;
    if (href.startsWith('./')) href = '/banks/math/' + href.replace(/^\.\//, '');
    if (!href.includes('resume=1')) href += (href.includes('?') ? '&' : '?') + 'resume=1';
    cont.href = href;
  } else {
    cont.hidden = true;
  }
}

function renderCourseTabs() {
  const tabsEl = document.getElementById('courseTabs');
  if (!tabsEl) return;
  const list = getAvailableCourses();
  tabsEl.innerHTML = '';
  if (!list.length) { tabsEl.style.display = 'none'; return; }
  tabsEl.style.display = '';
  list.forEach(c => {
    const btn = document.createElement('button');
    btn.className = 'course-tab' + (c.name === getCurrentCourse() ? ' active' : '');
    btn.innerHTML = escapeHtml(c.short || c.name) + '<span class="cnt">' + c.question_count + '</span>';
    btn.onclick = () => switchCourse(c.name);
    btn.dataset.course = c.name;
    tabsEl.appendChild(btn);
  });
}

function renderMobileCourseSelect() {
  const sel = document.getElementById('mobileCourseSelect');
  if (!sel) return;
  sel.innerHTML = '';
  const list = getAvailableCourses();
  list.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = c.short || c.name;
    if (c.name === getCurrentCourse()) opt.selected = true;
    sel.appendChild(opt);
  });
}

async function switchCourse(course) {
  if (course === selectedCourse) return;
  selectedCourse = course;
  selectedChapter = '';

  document.getElementById('resultText').textContent = '正在切换课程…';
  await loadBankData(course);

  currentChapters = getCurrentChapters();
  buildAllQuestions();
  sanitizeChoiceOnlySelection();
  refreshCursorKey();

  renderCourseTabs();
  renderMobileCourseSelect();
  currentPage = 1;
  renderChapters();
  renderStats();
  renderMarkDashboard();
  applyFilters();
  updateResumeBar();
  updateChapterCursorUI();
  setTimeout(flushLocalTextNotes, 400);
}

// ========================
// Sidebar - 两级折叠树（大章 → 小节；无第三级「选择题」节点）
// 内部筛选键仍为 l1|l2|选择题，兼容旧 URL
// ========================
function buildChapterTree() {
  if (_COV) {
    return _COV.buildChapterTreeMap(currentChapters, CHOICE_ONLY_MODE);
  }
  const l1Map = new Map();
  for (const ch of currentChapters) {
    const count = ch.question_count || (ch.questions && ch.questions.length) || 0;
    if (count <= 0) continue;
    const l1 = ch.l1_name || '?';
    const l2 = ch.l2_name || '?';
    const sec = ch.section_type || '?';
    if (CHOICE_ONLY_MODE && sec && String(sec).includes('解答')) continue;
    if (CHOICE_ONLY_MODE && sec && !isChoiceQuestionType(sec) && !String(sec).includes('选择')) continue;
    if (!l1Map.has(l1)) l1Map.set(l1, { name: l1, total: 0, l2Map: new Map() });
    const l1Node = l1Map.get(l1);
    l1Node.total += count;
    if (!l1Node.l2Map.has(l2)) {
      l1Node.l2Map.set(l2, {
        name: l2,
        total: 0,
        sections: [],
        l2Key: l1 + '|' + l2,
        filterKey: '',
        key: '',
      });
    }
    const l2Node = l1Node.l2Map.get(l2);
    l2Node.total += count;
    const secKey = l1 + '|' + l2 + '|' + sec;
    l2Node.sections.push({ name: ch.name, section_type: sec, question_count: count, key: secKey });
    if (!l2Node.filterKey || sec === '选择题') {
      l2Node.filterKey = secKey;
      l2Node.key = secKey;
    }
  }
  for (const [l1Name, l1Node] of [...l1Map.entries()]) {
    for (const [l2Key, l2Node] of [...l1Node.l2Map.entries()]) {
      if (!l2Node.sections.length || l2Node.total <= 0) l1Node.l2Map.delete(l2Key);
      else if (!l2Node.filterKey) {
        l2Node.filterKey = l2Node.sections[0].key;
        l2Node.key = l2Node.filterKey;
      }
    }
    if (!l1Node.l2Map.size || l1Node.total <= 0) l1Map.delete(l1Name);
  }
  return l1Map;
}

function makeToggle(text, count, extraClass, dataset, unsafe) {
  const btn = document.createElement('button');
  const cls = extraClass || '';
  btn.className = 'tree-toggle ' + cls;
  if (dataset) btn.dataset.key = dataset;
  const label = unsafe ? text : escapeHtml(text);
  const isLeaf = /\bleaf\b/.test(cls);
  // 叶子（二级小节）无展开箭头；一级保留 chevron
  const arrowHtml = isLeaf
    ? '<span class="arrow leaf-spacer" aria-hidden="true"></span>'
    : '<span class="arrow"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg></span>';
  btn.innerHTML = arrowHtml + '<span style="flex:1">' + label + '</span><span class="mastery-counts" data-role="masteryCounts"></span><span class="count">' + count + '</span>';
  return btn;
}

function l2NodeMatchesSelected(l2Node, selected) {
  if (!selected || !l2Node) return false;
  if (_COV && typeof _COV.l2MatchesSelection === 'function') {
    return _COV.l2MatchesSelection(l2Node, selected);
  }
  if (String(selected).includes('解答')) return false;
  const fk = l2Node.filterKey || l2Node.key || '';
  if (selected === fk) return true;
  const l2k = l2Node.l2Key || '';
  if (l2k && (selected === l2k || selected.indexOf(l2k + '|') === 0)) return true;
  return false;
}

function renderChapters() {
  const container = document.getElementById('chapterList');
  container.innerHTML = '';

  const allWrap = document.createElement('div');
  const allItem = makeToggle('全部章节', allQuestions.length, 'tree-l1 all-item' + (selectedChapter ? '' : ' active'), '__all__');
  allItem.onclick = (e) => {
    e.stopPropagation();
    selectChapter('', allItem);
  };
  allWrap.appendChild(allItem);
  container.appendChild(allWrap);

  const tree = buildChapterTree();

  for (const [l1Name, l1Node] of tree.entries()) {
    const l1Wrap = document.createElement('div');
    const l1Active = selectedChapter === l1Name;
    const l1Btn = makeToggle(l1Name, l1Node.total, 'tree-l1' + (l1Active ? ' active' : ''), l1Name);
    if (l1Active) l1Btn.classList.add('expanded');
    const l1Children = document.createElement('div');
    l1Children.className = 'tree-children' + (l1Active ? ' show' : '');

    l1Btn.onclick = (e) => {
      e.stopPropagation();
      const exp = l1Btn.classList.toggle('expanded');
      l1Children.classList.toggle('show', exp);
    };

    for (const [l2Name, l2Node] of l1Node.l2Map.entries()) {
      if (!l2Node.total) continue;
      const filterKey = l2Node.filterKey || l2Node.key || (l1Name + '|' + l2Name + '|选择题');
      const l2Wrap = document.createElement('div');
      l2Wrap.className = 'tree-l2-wrap';
      // 二级即叶子：直接筛选该小节全部选择题，不再渲染「选择题」第三级
      const l2Btn = makeToggle(l2Name, l2Node.total, 'tree-l2 leaf', filterKey);
      l2Btn.dataset.l2Key = l2Node.l2Key || (l1Name + '|' + l2Name);
      l2Btn.dataset.filterKey = filterKey;
      l2Btn.setAttribute('aria-label', l2Name + '，' + l2Node.total + ' 题');
      l2Btn.onclick = (e) => {
        e.stopPropagation();
        l1Btn.classList.add('expanded');
        l1Children.classList.add('show');
        selectChapter(filterKey, l2Btn);
      };
      l2Wrap.appendChild(l2Btn);
      l1Children.appendChild(l2Wrap);
    }

    l1Wrap.appendChild(l1Btn);
    l1Wrap.appendChild(l1Children);
    container.appendChild(l1Wrap);
  }

  updateChapterCursorUI();

  let matchedSelected = !selectedChapter || tree.has(selectedChapter);
  if (selectedChapter) {
    const buttons = container.querySelectorAll('.tree-l2.leaf');
    for (const btn of buttons) {
      const l2Meta = {
        filterKey: btn.dataset.filterKey || btn.dataset.key || '',
        key: btn.dataset.key || '',
        l2Key: btn.dataset.l2Key || '',
      };
      if (l2NodeMatchesSelected(l2Meta, selectedChapter)) {
        matchedSelected = true;
        // 规范为内部 filterKey，保证筛选精确
        if (l2Meta.filterKey && selectedChapter !== l2Meta.filterKey) {
          selectedChapter = l2Meta.filterKey;
        }
        btn.classList.add('active');
        let parent = btn.parentElement;
        while (parent) {
          if (parent.classList.contains('tree-children')) {
            parent.classList.add('show');
            const toggle = parent.previousElementSibling;
            if (toggle && toggle.classList.contains('tree-toggle')) toggle.classList.add('expanded');
          }
          parent = parent.parentElement;
        }
        break;
      }
    }
    // 幽灵选中：旧解答题章节等已不可见 → 回退全部章节
    if (!matchedSelected) {
      selectedChapter = '';
      allItem.classList.add('active');
    }
  }

  refreshChapterMastery();
}

function computeChapterMastery() {
  const map = new Map();
  for (const q of allQuestions) {
    const key = q.chapterKey || '';
    if (!map.has(key)) {
      map.set(key, { mastered: 0, familiar: 0, unknown: 0, unmarked: 0 });
    }
    const c = map.get(key);
    const st = getMastery(q);
    if (st === 'mastered') c.mastered++;
    else if (st === 'familiar') c.familiar++;
    else if (st === 'unknown') c.unknown++;
    else c.unmarked++;
  }
  return map;
}

function addMasteryCounts(a, b) {
  return {
    mastered: a.mastered + b.mastered,
    familiar: a.familiar + b.familiar,
    unknown: a.unknown + b.unknown,
    unmarked: a.unmarked + b.unmarked,
  };
}

function zeroMastery() {
  return { mastered: 0, familiar: 0, unknown: 0, unmarked: 0 };
}

function masteryCountsForKey(map, key) {
  if (key === '__all__') {
    let total = zeroMastery();
    for (const c of map.values()) total = addMasteryCounts(total, c);
    return total;
  }
  const parts = key.split('|');
  if (parts.length >= 3) {
    return map.get(key) || zeroMastery();
  }
  const prefix = key + '|';
  let total = zeroMastery();
  for (const [k, c] of map.entries()) {
    if (k.startsWith(prefix)) total = addMasteryCounts(total, c);
  }
  return total;
}

function renderMasteryCounts(el, counts) {
  const container = el.querySelector('[data-role="masteryCounts"]');
  if (!container) return;
  const pieces = [];
  if (counts.mastered) pieces.push('<span class="mc-mastered">' + counts.mastered + '</span>');
  if (counts.familiar) pieces.push('<span class="mc-familiar">' + counts.familiar + '</span>');
  if (counts.unknown) pieces.push('<span class="mc-unknown">' + counts.unknown + '</span>');
  container.innerHTML = pieces.join('');
}

function refreshChapterMastery() {
  if (!allQuestions.length) return;
  const map = computeChapterMastery();
  document.querySelectorAll('#chapterList .tree-toggle').forEach(btn => {
    const key = btn.dataset.key || '';
    if (!key) return;
    renderMasteryCounts(btn, masteryCountsForKey(map, key));
  });
}

function selectChapter(key, btn) {
  selectedChapter = key;
  document.querySelectorAll('.tree-toggle.active').forEach(el => el.classList.remove('active'));
  if (btn) btn.classList.add('active');
  currentPage = 1;
  applyFilters();
  if (window.innerWidth <= 768) {
    document.getElementById('sidebar').classList.remove('open');
  }
}

// ========================
// Stats
// ========================
let activeStat = 'all';
let activeStatusFilter = '';

function renderStats() {
  const types = {};
  const counts = {sub: 0, image: 0};
  let favCount = 0, unmarkedCount = 0;
  const masteryCounts = {mastered: 0, familiar: 0, unknown: 0};
  let wrongCount = 0, doneCount = 0;
  allQuestions.forEach(q => {
    types[q.type] = (types[q.type] || 0) + 1;
    if (q.sub_questions) counts.sub++;
    if (q.has_image) counts.image++;
    if (isFavorite(q)) favCount++;
    const mastery = getMastery(q);
    if (masteryCounts[mastery] !== undefined) masteryCounts[mastery]++;
    else unmarkedCount++;
    const pr = getPracticeResult(q);
    if (pr === 'wrong') wrongCount++;
    if (pr === 'correct' || pr === 'wrong') doneCount++;
  });

  // 题型 pill：仅实际可见且 count>0；绝不硬编码「解答 0」
  const typeStats = _COV
    ? _COV.buildTypeStatItems(types)
    : Object.keys(types).filter(t => types[t] > 0).map(t => ({
        label: t === '选择题' ? '选择' : t.replace(/题$/, ''),
        value: types[t],
        action: t,
      }));

  const stats = [
    {label: '总题数', value: allQuestions.length, action: 'all'},
    ...typeStats,
    {label: '子问', value: counts.sub, action: 'sub'},
    {label: '图片', value: counts.image, action: 'image'},
    // 状态统计即使为 0 也保留
    {label: '未标', value: unmarkedCount, action: 'unmarked', kind: 'status'},
    {label: '收藏', value: favCount, action: 'favorite', kind: 'status'},
    {label: '已掌握', value: masteryCounts.mastered, action: 'mastered', kind: 'status'},
    {label: '不熟', value: masteryCounts.familiar, action: 'familiar', kind: 'status'},
    {label: '不会', value: masteryCounts.unknown, action: 'unknown', kind: 'status'},
    {label: '错题', value: wrongCount, action: 'wrong', kind: 'status'},
    {label: '已做', value: doneCount, action: 'done', kind: 'status'},
  ];

  const container = document.getElementById('statsRow');
  container.innerHTML = stats.map(s => {
    const active = s.kind === 'status'
      ? activeStatusFilter === s.action
      : (!activeStatusFilter && activeStat === s.action);
    return `<div class="stat-pill ${active ? 'active' : ''}" data-stat="${s.action}" data-kind="${s.kind || ''}"><strong>${s.value}</strong>${s.label}</div>`;
  }).join('');

  container.querySelectorAll('.stat-pill').forEach(item => {
    item.addEventListener('click', () => {
      // 顶部统计胶囊属于全局筛选，清空已选章节以展示全部相关题目
      selectedChapter = '';
      const action = item.dataset.stat;
      const kind = item.dataset.kind;
      if (kind === 'status') {
        activeStatusFilter = activeStatusFilter === action ? '' : action;
        if (activeStatusFilter) {
          activeStat = 'all';
          document.getElementById('typeFilter').value = '';
          document.getElementById('featureFilter').value = '';
        }
      } else {
        activeStatusFilter = '';
        activeStat = action;
        if (action === 'all') {
          document.getElementById('typeFilter').value = '';
          document.getElementById('featureFilter').value = '';
        } else if (action === 'sub') {
          document.getElementById('typeFilter').value = '';
          document.getElementById('featureFilter').value = 'sub';
        } else if (action === 'image') {
          document.getElementById('typeFilter').value = '';
          document.getElementById('featureFilter').value = 'image';
        } else {
          document.getElementById('typeFilter').value = action;
          document.getElementById('featureFilter').value = '';
        }
      }
      currentPage = 1;
      applyFilters();
      renderChapters();
      renderStats();
    });
  });
}

// ========================
// Filtering & Search
// ========================
function filterQuestions(source, opts) {
  const tokenSplitRe = /[\s,.;:!?。，；：！？、（）()\[\]"'"]+/;
  return source.filter(q => {
    if (!qualityVisible(q)) return false;
    // 章级深链（如 树与二叉树，无 '|'）：匹配该章所有小节
    if (opts.chapter) {
      if (opts.chapter.indexOf('|') === -1) {
        if (String(q.chapterKey || '').split('|')[0] !== opts.chapter) return false;
      } else if (q.chapterKey !== opts.chapter) return false;
    }
    if (opts.type && q.type !== opts.type) return false;
    if (opts.feature === 'sub' && !q.sub_questions) return false;
    if (opts.feature === 'image' && !q.has_image) return false;
    if (opts.status) {
      if (opts.status === 'unmarked') {
        if (getMastery(q)) return false;
      } else if (opts.status === 'favorite') {
        if (!isFavorite(q)) return false;
      } else if (opts.status === 'done' || opts.status === 'wrong') {
        const pr = getPracticeResult(q);
        if (opts.status === 'done' && pr !== 'correct' && pr !== 'wrong') return false;
        if (opts.status === 'wrong' && pr !== 'wrong') return false;
      } else if (MASTERY_KEYS.has(opts.status)) {
        if (getMastery(q) !== opts.status) return false;
      } else {
        if (getStatus(q) !== opts.status) return false;
      }
    }
    if (opts.search) {
      const term = opts.search;
      // 1) 连续子串命中：保持原有搜索行为
      if (q._searchText.includes(term)) return true;
      // 2) 多词分词命中：每个长度>1的词都出现在题目 token 集合中
      const words = term.split(tokenSplitRe).filter(w => w.length > 1);
      if (words.length > 1 && words.every(w => q._searchTokens.has(w))) return true;
      return false;
    }
    return true;
  });
}

function applyFilters() {
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  const type = document.getElementById('typeFilter').value;
  const feature = document.getElementById('featureFilter').value;

  if (!activeStatusFilter) {
    if (!type && !feature) activeStat = 'all';
    else if (feature === 'sub') activeStat = 'sub';
    else if (feature === 'image') activeStat = 'image';
    else if (type) activeStat = type;
  }

  filteredQuestions = filterQuestions(allQuestions, {chapter: selectedChapter, type, feature, status: activeStatusFilter, search});

  // 排序
  const sortBy = document.getElementById('sortSelect') ? document.getElementById('sortSelect').value : 'default';
  if (sortBy && sortBy !== 'default') {
    filteredQuestions = [...filteredQuestions].sort((a, b) => {
      if (sortBy === 'id') {
        return displayId(a).localeCompare(displayId(b), 'zh', {numeric: true});
      } else if (sortBy === 'page') {
        return (a.page || 0) - (b.page || 0);
      } else if (sortBy === 'chapter') {
        return (a.chapterKey || '').localeCompare(b.chapterKey || '', 'zh');
      }
      return 0;
    });
  }

  // 展示用：去掉末尾「|选择题」，避免结果栏再出现题型层
  let chapterLabel = '';
  if (selectedChapter) {
    chapterLabel = selectedChapter
      .replace(/\|选择题$/u, '')
      .replace(/\|/g, ' · ');
  }
  document.getElementById('resultText').innerHTML =
    `共 <strong>${filteredQuestions.length}</strong> 道题目${chapterLabel ? ' · <span style="color:var(--text-secondary)">' + escapeHtml(chapterLabel) + '</span>' : ''}`;

  currentPage = Math.min(currentPage, Math.max(1, getTotalPages()));
  renderGrid(search);
  renderPagination();
  renderStats();
  syncUrl();
}

// ========================
// Grid Rendering（卡片网格，对齐数学题库）
// ========================
function masteryBadgeHtml(q) {
  const masteryKey = getMastery(q);
  const m = MASTERY_STATUSES.find(x => x.key === masteryKey);
  if (!m) return '';
  return `<span class="card-mark mark-${m.cls}">${m.label}</span>`;
}

function renderMarkDashboard() {
  const el = document.getElementById('markDashboard');
  if (!el || !allQuestions.length) return;
  const counts = { mastered: 0, familiar: 0, unknown: 0, none: 0 };
  allQuestions.forEach(q => {
    const st = getMastery(q);
    if (st === 'mastered') counts.mastered++;
    else if (st === 'familiar') counts.familiar++;
    else if (st === 'unknown') counts.unknown++;
    else counts.none++;
  });
  const total = allQuestions.length || 1;
  const pct = (n) => Math.round((n / total) * 100);
  const marked = counts.mastered + counts.familiar + counts.unknown;
  el.innerHTML = `
    <div class="mark-dash-head">
      <span class="mark-dash-title">做题统计</span>
      <span class="mark-dash-meta">已标记 ${marked} / ${allQuestions.length} · ${pct(marked)}%</span>
    </div>
    <div class="mark-dash-bar" aria-hidden="true">
      <span class="seg mastered" style="width:${pct(counts.mastered)}%"></span>
      <span class="seg familiar" style="width:${pct(counts.familiar)}%"></span>
      <span class="seg unknown" style="width:${pct(counts.unknown)}%"></span>
      <span class="seg none" style="width:${pct(counts.none)}%"></span>
    </div>
    <div class="mark-dash-legend">
      <button type="button" class="mark-leg" data-status="mastered"><i class="dot mastered"></i>已掌握 <b>${counts.mastered}</b> <em>${pct(counts.mastered)}%</em></button>
      <button type="button" class="mark-leg" data-status="familiar"><i class="dot familiar"></i>不熟 <b>${counts.familiar}</b> <em>${pct(counts.familiar)}%</em></button>
      <button type="button" class="mark-leg" data-status="unknown"><i class="dot unknown"></i>不会 <b>${counts.unknown}</b> <em>${pct(counts.unknown)}%</em></button>
      <button type="button" class="mark-leg" data-status="unmarked"><i class="dot none"></i>未标记 <b>${counts.none}</b> <em>${pct(counts.none)}%</em></button>
    </div>
  `;
  el.querySelectorAll('.mark-leg').forEach(btn => {
    btn.addEventListener('click', () => {
      activeStatusFilter = btn.dataset.status === activeStatusFilter ? '' : btn.dataset.status;
      activeStat = 'all';
      currentPage = 1;
      applyFilters();
    });
  });
}

function renderGrid(search) {
  const grid = document.getElementById('questionGrid');
  const start = (currentPage - 1) * pageSize;
  const pageQs = filteredQuestions.slice(start, start + pageSize);

  if (pageQs.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column:1/-1">
        <h3>未找到题目</h3>
        <p>尝试调整筛选条件或搜索关键词</p>
        <button type="button" class="btn btn-secondary btn-sm" onclick="resetAllFilters()">清空筛选</button>
      </div>`;
    return;
  }

  grid.innerHTML = pageQs.map((q, i) => {
    const typeClass = q.type === '选择题' ? 'choice' : 'nonchoice';
    const tags = [];
    if (q.sub_questions) tags.push(`${q.sub_questions.length} 个子问`);
    if (q.has_image) tags.push('含图片');
    if (q.options) tags.push('有选项');
    const chShort = (q.chapter || '').split('·')[0].trim() || q.chapter || '';
    return `
      <div class="question-card" tabindex="0" role="button" aria-label="${displayId(q)} ${q.type}" data-index="${start + i}">
        <div class="card-header">
          <span class="card-id">${escapeHtml(chShort)} · ${escapeHtml(displayId(q))}</span>
          <div class="card-badges">
            ${masteryBadgeHtml(q)}
            <span class="card-type ${typeClass}">${escapeHtml(q.type || '')}</span>
          </div>
        </div>
        <div class="card-chapter">第 ${q.page || '—'} 页</div>
        <div class="card-content" id="card-text-${start + i}"></div>
        <div class="card-tags">${tags.map(t => `<span class="card-tag">${escapeHtml(t)}</span>`).join('')}</div>
      </div>
    `;
  }).join('');

  pageQs.forEach((q, i) => {
    const el = document.getElementById(`card-text-${start + i}`);
    if (el) {
      const preview = (!q.content || q.content.startsWith('（本题无主题干') || q.content.trim() === '')
        && q.sub_questions && q.sub_questions.length > 0
          ? q.sub_questions[0]
          : q.content;
      el.textContent = normalizeDisplayText(preview);
      renderKatex(el);
      if (search) highlightText(el, search);
    }
  });
}

function renderPagination() {
  const totalPages = getTotalPages();
  const p = document.getElementById('pagination');

  p.innerHTML = `
    <button onclick="changePage(1)" ${currentPage <= 1 ? 'disabled' : ''}>首页</button>
    <button onclick="changePage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>上一页</button>
    <span class="page-info">${currentPage} / ${totalPages}</span>
    <button onclick="changePage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一页</button>
    <button onclick="changePage(${totalPages})" ${currentPage >= totalPages ? 'disabled' : ''}>末页</button>
    <span class="page-jump">跳转 <input type="number" min="1" max="${totalPages}" value="${currentPage}" onkeydown="if(event.key==='Enter')changePage(+this.value)"> 页</span>
  `;
}

function changePage(p) {
  if (p < 1 || p > getTotalPages()) return;
  currentPage = p;
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  renderGrid(search);
  renderPagination();
  document.getElementById('content').scrollTop = 0;
  syncUrl();
}

// ========================
// Shared Rendering
// ========================
/** 选项按 A/B/C/D 字母序展开。OCR/双栏解析可能导致 JSON 键序为 A,C,D,B。 */
function sortedOptionEntries(options) {
  if (!options) return [];
  return Object.entries(options).sort(([a], [b]) => String(a).localeCompare(String(b)));
}

function renderOptionsHtml(q) {
  if (!q.options) return '';
  const opts = sortedOptionEntries(q.options).map(([k, v]) => `
    <div class="option-item" data-key="${k}">
      <span class="option-key">${k}.</span>
      <span class="opt-math"></span>
    </div>
  `).join('');
  return `<div class="q-options">${opts}</div>`;
}

function renderSubHtml(q) {
  if (!q.sub_questions || !q.sub_questions.length) return '';
  return `
    <div class="q-sub">
      <div class="sub-label">子问题</div>
      ${q.sub_questions.map((s, i) => `<div class="sub-item" data-role="sub">${escapeHtml(s)}</div>`).join('')}
    </div>
  `;
}

function answerHtml(q) {
  const a = q.answer;
  if (!a) return '';
  const choice = a.choice;
  const expl = a.explanation && a.explanation.trim();
  if (!choice && !expl) return '';
  return `
    <div class="q-answer-toggle" data-role="ansToggle">
      <button type="button" class="reveal-answer-btn" data-role="revealBtn">显示答案</button>
    </div>
    <div class="q-answer" data-role="ans" hidden>
      ${choice ? `<span class="q-answer-choice">答案：${escapeHtml(choice)}</span>` : ''}
      ${expl ? `<div class="q-answer-explain" data-role="qans"></div>` : ''}
    </div>
  `;
}

function practiceMasteryHtml() {
  return `
    <div class="practice-mastery" data-role="practiceMastery" hidden>
      <div class="practice-mastery-label">这道题掌握得怎么样？</div>
      <div class="practice-mastery-btns">
        <button type="button" class="btn btn-mastery mastered" data-role="masteryBtn" data-mastery="mastered">已掌握</button>
        <button type="button" class="btn btn-mastery familiar" data-role="masteryBtn" data-mastery="familiar">不熟</button>
        <button type="button" class="btn btn-mastery unknown" data-role="masteryBtn" data-mastery="unknown">不会</button>
      </div>
    </div>
  `;
}

function practiceAnswerHtml(q) {
  const isChoice = q.type === '选择题';
  if (isChoice) {
    return `
      <div class="practice-feedback" data-role="practiceFeedback" hidden>
        <div class="feedback-result" data-role="feedbackResult"></div>
        <div class="q-answer-explain" data-role="feedbackExplain"></div>
      </div>
      ${practiceMasteryHtml()}
    `;
  }
  return answerHtml(q) + `
    <div class="practice-selfgrade" data-role="selfGrade" hidden>
      <button type="button" class="btn btn-secondary" data-role="markCorrect">我做对了</button>
      <button type="button" class="btn" style="border:1px solid var(--danger);color:var(--danger)" data-role="markWrong">我做错了</button>
    </div>
    ${practiceMasteryHtml()}
  `;
}

function bindRevealAnswer(container) {
  const btn = container.querySelector('[data-role="revealBtn"]');
  if (!btn) return;
  btn.onclick = () => revealAnswerBox(container, container._q);
}

function judgeChoice(container, q, selectedKey) {
  if (container._submitted) return null;
  container._submitted = true;
  const correct = q.answer && q.answer.choice;
  const isCorrect = selectedKey === correct;

  const opts = container.querySelectorAll('.option-item');
  opts.forEach(o => {
    o.classList.add('disabled');
    const key = o.dataset.key;
    if (key === correct) o.classList.add('correct');
    if (key === selectedKey && !isCorrect) o.classList.add('wrong');
  });

  recordPracticeResult(q, isCorrect);
  return isCorrect;
}

/** 连续多空题：答案为 2+ 个字母（如 CD），需按空序依次点击选项 */
function isOrderedChoice(q) {
  return orderedCorrect(q).length > 1;
}

function orderedCorrect(q) {
  return ((q.answer && q.answer.choice) || '').replace(/[^A-F]/gi, '').toUpperCase();
}

function showChoiceFeedback(container, q, isCorrect, seq) {
  const fb = container.querySelector('[data-role="practiceFeedback"]');
  if (fb) {
    fb.hidden = false;
    fb.classList.remove('correct', 'wrong');
    fb.classList.add(isCorrect ? 'correct' : 'wrong');
    const res = fb.querySelector('[data-role="feedbackResult"]');
    if (res) {
      let text = isCorrect ? '回答正确' : '回答错误';
      if (!isCorrect && seq) text += `（你的答案：${seq}，正确答案：${orderedCorrect(q)}）`;
      res.textContent = text;
      res.className = 'feedback-result ' + (isCorrect ? 'correct' : 'wrong');
    }
    const expl = fb.querySelector('[data-role="feedbackExplain"]');
    if (expl && q.answer && q.answer.explanation) {
      fillExplanation(expl, q.answer.explanation, '解析：');
    }
  }
  showPracticeMastery(container);
}

function bindOrderedChoice(container, q, onJudged) {
  const correct = orderedCorrect(q);
  let seqBar = container.querySelector('[data-role="seqBar"]');
  if (!seqBar) {
    seqBar = document.createElement('div');
    seqBar.className = 'practice-seq';
    seqBar.dataset.role = 'seqBar';
    seqBar.innerHTML = '<span data-role="seqHint"></span>：<strong data-role="seqText"></strong> <button type="button" class="btn btn-secondary seq-undo" data-role="seqUndo">↩ 撤销</button>';
    const optsBox = container.querySelector('.q-options');
    if (optsBox && optsBox.parentNode) optsBox.parentNode.insertBefore(seqBar, optsBox.nextSibling);
    else container.appendChild(seqBar);
  }
  const seqText = seqBar.querySelector('[data-role="seqText"]');
  const undoBtn = seqBar.querySelector('[data-role="seqUndo"]');
  seqBar.hidden = false;
  const hint = seqBar.querySelector('[data-role="seqHint"]');
  if (hint) hint.textContent = `本题 ${correct.length} 个空，请按顺序点击选项`;
  container._seq = '';
  const syncSeq = () => { if (seqText) seqText.textContent = container._seq.split('').join(' → '); };

  container.querySelectorAll('.option-item').forEach(opt => {
    opt.addEventListener('click', () => {
      if (container._submitted) return;
      container._seq += opt.dataset.key;
      opt.classList.add('picked');
      syncSeq();
      if (container._seq.length < correct.length) return;
      container._submitted = true;
      const isCorrect = container._seq === correct;
      container.querySelectorAll('.option-item').forEach(o => {
        o.classList.add('disabled');
        o.classList.remove('picked');
        if (correct.includes(o.dataset.key)) o.classList.add('correct');
      });
      seqBar.hidden = true;
      recordPracticeResult(q, isCorrect);
      onJudged(isCorrect, container._seq);
    });
  });
  if (undoBtn) undoBtn.onclick = () => {
    if (container._submitted || !container._seq) return;
    container._seq = container._seq.slice(0, -1);
    syncSeq();
  };
}

function recordPracticeResult(q, isCorrect) {
  setPracticeResult(q, isCorrect);
  updateReviewSchedule(q, isCorrect);
  const key = questionKey(q);
  const existing = practiceResults.find(r => questionKey(r.q) === key);
  if (existing) existing.correct = isCorrect;
  else practiceResults.push({q, correct: isCorrect});
  refreshDueBadge();
  saveProgress();
}

function revealAnswerBox(container, q) {
  const ansBox = container.querySelector('[data-role="ans"]');
  const ansText = container.querySelector('[data-role="qans"]');
  const toggle = container.querySelector('[data-role="ansToggle"]');
  if (!ansBox) return;
  if (q && q.answer) {
    if (ansText && q.answer.explanation) {
      fillExplanation(ansText, q.answer.explanation);
    }
    ansBox.hidden = false;
    if (toggle) toggle.style.display = 'none';
  }
}

function bindPracticeInteractions(container, q) {
  const isChoice = q.type === '选择题';
  if (isChoice && isOrderedChoice(q)) {
    bindOrderedChoice(container, q, (ok, seq) => showChoiceFeedback(container, q, ok, seq));
    return;
  }
  if (isChoice) {
    const opts = container.querySelectorAll('.option-item');
    opts.forEach(opt => {
      opt.addEventListener('click', () => {
        const selected = opt.dataset.key;
        const isCorrect = judgeChoice(container, q, selected);
        if (isCorrect === null) return;

        const fb = container.querySelector('[data-role="practiceFeedback"]');
        if (fb) {
          fb.hidden = false;
          fb.classList.remove('correct', 'wrong');
          fb.classList.add(isCorrect ? 'correct' : 'wrong');
          const res = fb.querySelector('[data-role="feedbackResult"]');
          if (res) {
            res.textContent = isCorrect ? '回答正确' : '回答错误';
            res.className = 'feedback-result ' + (isCorrect ? 'correct' : 'wrong');
          }
          const expl = fb.querySelector('[data-role="feedbackExplain"]');
          if (expl && q.answer && q.answer.explanation) {
            fillExplanation(expl, q.answer.explanation, '解析：');
          }
        }

        showPracticeMastery(container);
      });
    });
  } else {
    bindRevealAnswer(container);
    const btn = container.querySelector('[data-role="revealBtn"]');
    const selfGrade = container.querySelector('[data-role="selfGrade"]');
    if (btn && selfGrade) {
      const oldClick = btn.onclick;
      btn.onclick = () => {
        oldClick && oldClick();
        selfGrade.hidden = false;
        btn.disabled = true;
      };
    }
    const markCorrect = container.querySelector('[data-role="markCorrect"]');
    const markWrong = container.querySelector('[data-role="markWrong"]');
    if (markCorrect) markCorrect.onclick = () => { recordPracticeResult(q, true); selfGrade.hidden = true; showPracticeMastery(container); };
    if (markWrong) markWrong.onclick = () => { recordPracticeResult(q, false); selfGrade.hidden = true; showPracticeMastery(container); };
  }
}

function showPracticeMastery(container) {
  const box = container.querySelector('[data-role="practiceMastery"]');
  if (!box) return;
  box.hidden = false;
  box.querySelectorAll('[data-role="masteryBtn"]').forEach(btn => {
    btn.onclick = () => {
      setMastery(container._q, btn.dataset.mastery);
      box.hidden = true;
    };
  });
}

function restorePracticeState(container, q) {
  const key = questionKey(q);
  const record = practiceResults.find(r => questionKey(r.q) === key);
  if (!record) return;

  const masteryBox = container.querySelector('[data-role="practiceMastery"]');
  if (masteryBox && getMastery(q)) masteryBox.hidden = true;

  if (q.type === '选择题') {
    container._submitted = true;
    const correct = orderedCorrect(q) || (q.answer && q.answer.choice);
    const correctLetters = new Set(String(correct || '').split(''));
    const opts = container.querySelectorAll('.option-item');
    opts.forEach(o => {
      o.classList.add('disabled');
      if (correctLetters.has(o.dataset.key)) o.classList.add('correct');
    });
    const fb = container.querySelector('[data-role="practiceFeedback"]');
    if (fb) {
      fb.hidden = false;
      fb.classList.add(record.correct ? 'correct' : 'wrong');
      const res = fb.querySelector('[data-role="feedbackResult"]');
      if (res) {
        res.textContent = record.correct ? '回答正确' : '回答错误';
        res.className = 'feedback-result ' + (record.correct ? 'correct' : 'wrong');
      }
      const expl = fb.querySelector('[data-role="feedbackExplain"]');
      if (expl && q.answer && q.answer.explanation) {
        fillExplanation(expl, q.answer.explanation, '解析：');
      }
    }
  } else {
    const btn = container.querySelector('[data-role="revealBtn"]');
    const ansBox = container.querySelector('[data-role="ans"]');
    const ansText = container.querySelector('[data-role="qans"]');
    if (btn) { btn.disabled = true; btn.parentElement.style.display = 'none'; }
    if (ansBox) ansBox.hidden = false;
    if (ansText && q.answer && q.answer.explanation) {
      fillExplanation(ansText, q.answer.explanation);
    }
  }
}

/** 裁剪图文件名里的页码须与题目页接近，避免同题号（如 X10）串到别章的图 */
function cropPageMatchesQuestion(cropped, qPage) {
  if (qPage == null || qPage === '') return true;
  const m = String(cropped || '').match(/page_(\d+)_/i);
  if (!m) return true;
  return Math.abs(parseInt(m[1], 10) - Number(qPage)) <= 1;
}

/** 从 image_ref 或解析里的「题目图片：crops/...」解析可显示的题图 */
function resolveQuestionImageRef(q) {
  if (q && q.image_ref && (q.image_ref.cropped || q.image_ref.page)) {
    const cropped = q.image_ref.cropped || '';
    if (!cropped || cropPageMatchesQuestion(cropped, q.page)) {
      return q.image_ref;
    }
  }
  const expl = (q && q.answer && q.answer.explanation) || '';
  const m = String(expl).match(/题目图片\s*[：:]\s*(\S+)/);
  if (m) {
    const cropped = m[1].trim();
    if (cropPageMatchesQuestion(cropped, q && q.page)) {
      return {
        page: (q && q.page) || '',
        note: '题目配图',
        cropped,
      };
    }
  }
  return null;
}

function questionBodyHtml(q, mode) {
  const isPractice = mode === 'practice';
  const imgRef = resolveQuestionImageRef(q);
  // 配图放在题干下方：题干写「如下图」时直接看到图，无需再点「查看原图」
  return `
    <div class="q-text" data-role="qtext"></div>
    ${imgRef ? imageHtml(imgRef) : ''}
    ${renderOptionsHtml(q)}
    ${renderSubHtml(q)}
    ${isPractice ? practiceAnswerHtml(q) : answerHtml(q)}
  `;
}

function isPipeRow(line) {
  const t = String(line || '').trim();
  return t.startsWith('|') && t.endsWith('|') && t.length > 1;
}

function splitPipeRow(line) {
  const t = String(line || '').trim();
  const inner = t.startsWith('|') ? t.slice(1) : t;
  const body = inner.endsWith('|') ? inner.slice(0, -1) : inner;
  return body.split('|').map((cell) => cell.trim());
}

function isSepRow(line) {
  const cells = splitPipeRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-+:?$/.test(cell.replace(/\s/g, '')));
}

function stemTableHtml(lines) {
  const rows = lines.filter((line) => !isSepRow(line)).map(splitPipeRow);
  if (!rows.length) return escapeHtml(lines.join('\n'));
  const head = rows[0] || [];
  const body = rows.slice(1);
  const th = head.map((cell) => '<th>' + (escapeHtml(cell) || '&nbsp;') + '</th>').join('');
  const tr = body.map((row) => '<tr>' + row.map((cell) => '<td>' + (escapeHtml(cell) || '&nbsp;') + '</td>').join('') + '</tr>').join('');
  return '<div class="stem-table"><table><thead><tr>' + th + '</tr></thead><tbody>' + tr + '</tbody></table></div>';
}

function fillStemText(el, raw) {
  const text = prepareMathText(raw);
  const lines = String(text || '').split('\n');
  // 题干可含多个 markdown 管道表；表前/表间/表后文字仍走 .stem-prose 纯文本
  const parts = [];
  let prose = [];
  const flushProse = () => {
    const t = prose.join('\n').replace(/^\n+|\n+$/g, '');
    prose = [];
    if (t) parts.push({ type: 'prose', text: t });
  };
  let i = 0;
  while (i < lines.length) {
    if (isPipeRow(lines[i]) && isSepRow(lines[i + 1] || '')) {
      flushProse();
      let end = i;
      while (end < lines.length && isPipeRow(lines[end])) end += 1;
      parts.push({ type: 'table', lines: lines.slice(i, end) });
      i = end;
    } else {
      prose.push(lines[i]);
      i += 1;
    }
  }
  flushProse();
  if (!parts.some((p) => p.type === 'table')) {
    el.textContent = text;
    return;
  }
  el.innerHTML = parts
    .map((p) => (p.type === 'table' ? stemTableHtml(p.lines) : '<div class="stem-prose"></div>'))
    .join('');
  const proses = el.querySelectorAll('.stem-prose');
  let pi = 0;
  parts.forEach((p) => {
    if (p.type === 'prose' && proses[pi]) {
      proses[pi].textContent = p.text;
      pi += 1;
    }
  });
}

function renderQuestionBody(container, q, mode) {
  container._submitted = false;
  const qtext = container.querySelector('[data-role="qtext"]');
  if (qtext) { fillStemText(qtext, q.content); renderKatex(qtext); }

  if (q.options) {
    const optMathEls = container.querySelectorAll('.opt-math');
    const entries = sortedOptionEntries(q.options);
    optMathEls.forEach((el, i) => {
      if (entries[i]) { el.textContent = prepareMathText(entries[i][1]); renderKatex(el); }
    });
  }

  if (q.sub_questions) {
    const subEls = container.querySelectorAll('[data-role="sub"]');
    q.sub_questions.forEach((s, i) => {
      if (subEls[i]) { subEls[i].textContent = prepareMathText(s); renderKatex(subEls[i]); }
    });
  }

  container._q = q;
  if (mode === 'practice') bindPracticeInteractions(container, q);
  else bindDetailInteractions(container, q);
}

function bindDetailInteractions(container, q) {
  // 选择题也要能点「显示答案」；先前只绑了选项点击，按钮是死的
  bindRevealAnswer(container);
  if (q.type === '选择题' && isOrderedChoice(q)) {
    bindOrderedChoice(container, q, (isCorrect, seq) => {
      revealAnswerBox(container, q);
      const ansBox = container.querySelector('[data-role="ans"]');
      if (ansBox) {
        let result = ansBox.querySelector('.detail-feedback-result');
        if (!result) {
          result = document.createElement('div');
          result.className = 'detail-feedback-result';
          ansBox.insertBefore(result, ansBox.firstChild);
        }
        result.classList.remove('correct', 'wrong');
        result.classList.add(isCorrect ? 'correct' : 'wrong');
        result.textContent = isCorrect
          ? '回答正确'
          : `回答错误（你的答案：${seq}，正确答案：${orderedCorrect(q)}）`;
      }
    });
    return;
  }
  if (q.type === '选择题') {
    container.querySelectorAll('.option-item').forEach(opt => {
      opt.addEventListener('click', () => {
        const isCorrect = judgeChoice(container, q, opt.dataset.key);
        if (isCorrect === null) return;
        revealAnswerBox(container, q);
        const ansBox = container.querySelector('[data-role="ans"]');
        if (ansBox) {
          let result = ansBox.querySelector('.detail-feedback-result');
          if (!result) {
            result = document.createElement('div');
            result.className = 'detail-feedback-result';
            ansBox.insertBefore(result, ansBox.firstChild);
          }
          result.classList.remove('correct', 'wrong');
          result.classList.add(isCorrect ? 'correct' : 'wrong');
          result.textContent = isCorrect ? '回答正确' : '回答错误';
        }
      });
    });
  }
}

// ========================
// Detail Modal
// ========================
function renderModalContent(q) {
  const container = document.getElementById('modalContent');
  // 刷题时不展示「相似题」，减少干扰（findSimilarQuestions 仍保留供以后开关）
  container.innerHTML = `
    <div class="q-chapter">${escapeHtml(q.chapter)} · 第 ${q.page} 页</div>
    <div class="q-id">${escapeHtml(displayId(q))} <span class="row-type ${q.type === '选择题' ? 'choice' : 'nonchoice'}">${q.type}</span> ${qualityBadgeHtml(q)}</div>
    ${questionBodyHtml(q)}
    <details class="q-notes" id="detailNotes">
      <summary>📝 我的笔记 <span class="notes-status" id="notesStatus"></span></summary>
      <textarea id="notesTextarea" placeholder="记录思路、口诀、易错点。公式：$h=\\log_2 n$；可直接粘贴图片" rows="6"></textarea>
      <p class="q-notes-hint">公式用 $...$ / $$...$$ / \\(...\\)；图片直接粘贴或点下方按钮插入，存在本浏览器。下方实时预览。</p>
      <div class="q-notes-preview" id="notesPreview" hidden></div>
      <div class="q-notes-actions">
        <button type="button" class="btn btn-secondary btn-sm" id="btnInsertNoteImg">🖼 插入图片</button>
        <button type="button" class="btn btn-secondary btn-sm" id="btnConvertNoteImg" title="把笔记里已插入的图片转为文字">📝 图中文字</button>
        <input type="file" id="noteImgInput" accept="image/*" hidden>
        <button type="button" class="btn btn-secondary btn-sm" id="btnCopyQ">📋 复制题目</button>
        <button type="button" class="btn btn-secondary btn-sm" id="btnReportIssue">⚠ 报告错误</button>
      </div>
    </details>
  `;
  renderQuestionBody(container, q);
  updateDetailStatusButtons(q);
  bindNotesUI(q);
  if (window.ViewerPlatformSync && ViewerPlatformSync.attachNoteReminderButton) {
    ViewerPlatformSync.attachNoteReminderButton(
      document.querySelector('#detailModal .modal-header-actions'),
      {
        bank: '408',
        uid: platformSourceUid(q),
        title: q.content || '',
        chapter: q.chapter || '',
      },
    );
  }
}

function bindNotesUI(q) {
  const ta = document.getElementById('notesTextarea');
  const preview = document.getElementById('notesPreview');
  const status = document.getElementById('notesStatus');
  const notesDetails = document.getElementById('detailNotes');
  if (!ta) return;
  const existing = getNote(q);
  ta.value = existing;
  if (existing) notesDetails.open = true;
  const updateStatus = () => {
    status.textContent = ta.value ? '（已保存）' : '';
  };
  const updatePreview = () => {
    if (!preview || !notesDetails) return;
    const text = ta.value;
    if (!text.trim()) {
      preview.hidden = true;
      preview.innerHTML = '';
      notesDetails.classList.remove('has-note-preview');
      return;
    }
    renderNotePreview(preview, text);
    preview.hidden = false;
    notesDetails.classList.add('has-note-preview');
  };
  updateStatus();
  updatePreview();
  let saveTimer;
  ta.addEventListener('input', () => {
    updatePreview();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      setNote(q, ta.value);
      updateStatus();
      syncOneTextNote(q);
    }, 400);
  });
  ta.addEventListener('paste', (e) => {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    const item = Array.from(items).find((it) => it.kind === 'file' && it.type && it.type.startsWith('image/'));
    if (!item) return;
    e.preventDefault();
    processNoteImage(item.getAsFile())
      .then((dataUrl) => {
        const token = storeNoteImage(dataUrl);
        insertTextAtCursor(ta, token ? `![图片](${token})` : `![图片](${dataUrl})`);
        maybeConvertNoteImage(ta, dataUrl);
      })
      .catch((err) => flashToast((err && err.message) || '图片插入失败'));
  });
  ta.addEventListener('blur', () => {
    setNote(q, ta.value);
    updateStatus();
    updatePreview();
    syncOneTextNote(q);
  });

  const imgBtn = document.getElementById('btnInsertNoteImg');
  const imgInput = document.getElementById('noteImgInput');
  if (imgBtn && imgInput) {
    imgBtn.onclick = () => imgInput.click();
    imgInput.onchange = () => {
      const file = imgInput.files && imgInput.files[0];
      imgInput.value = '';
      if (!file) return;
      processNoteImage(file)
        .then((dataUrl) => {
          const token = storeNoteImage(dataUrl);
          insertTextAtCursor(ta, token ? `![图片](${token})` : `![图片](${dataUrl})`);
          maybeConvertNoteImage(ta, dataUrl);
        })
        .catch((err) => flashToast((err && err.message) || '图片插入失败'));
    };
  }

  const convertImgBtn = document.getElementById('btnConvertNoteImg');
  if (convertImgBtn) convertImgBtn.onclick = () => convertFirstNoteImage(ta);

  const copyBtn = document.getElementById('btnCopyQ');
  if (copyBtn) copyBtn.onclick = () => copyQuestionToClipboard(q);

  const issueBtn = document.getElementById('btnReportIssue');
  if (issueBtn) issueBtn.onclick = () => reportQuestionIssue(q);
}

function copyQuestionToClipboard(q) {
  const lines = [];
  lines.push(`【${q.type}】${displayId(q)} · 第 ${q.page} 页 · ${q.chapter}`);
  if (q.content) lines.push('', q.content);
  if (q.options) {
    lines.push('');
    sortedOptionEntries(q.options).forEach(([k, v]) => lines.push(`${k}. ${v}`));
  }
  if (q.sub_questions) {
    lines.push('', '子问题：');
    q.sub_questions.forEach((s, i) => lines.push(`(${i + 1}) ${s}`));
  }
  if (q.answer && q.answer.choice) lines.push('', `答案：${q.answer.choice}`);
  if (q.answer && q.answer.explanation) lines.push(`解析：${q.answer.explanation}`);
  const note = getNote(q);
  if (note) lines.push('', `笔记：${stripNoteImages(note)}`);
  const text = lines.join('\n');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => flashToast('已复制到剪贴板'), () => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); flashToast('已复制到剪贴板'); } catch(e) { flashToast('复制失败，请手动复制'); }
  document.body.removeChild(ta);
}

function reportQuestionIssue(q) {
  const key = questionKey(q);
  const cur = (issuesMap[key] || []).slice();
  const kindRaw = prompt('错误类型：stem=题干/OCR，options=选项，answer=答案，explanation=解析，image=图片，other=其他', 'stem');
  const kind = ['stem', 'options', 'answer', 'explanation', 'image', 'other'].includes(String(kindRaw || '').trim())
    ? String(kindRaw).trim() : 'other';
  const choice = prompt('请简要描述该题的错误（将同步到平台质检队列）：', '');
  if (!choice) return;
  const at = new Date().toISOString();
  cur.push({at, text: choice, type: kind});
  issuesMap[key] = cur;
  saveIssues();
  const payload = buildQuestionIssuePayload(q, kind, choice, at);
  issueQueue = (issueQueue || []).filter(x => !(x.source_uid === payload.source_uid && x.issue_type === payload.issue_type));
  issueQueue.push(payload);
  saveIssueQueue();
  submitQuestionIssueQueue({silent: false});
  flashToast(isPlatformHost() ? '已提交错误反馈' : '已保存反馈；从平台打开题库后自动补传');
}

function buildQuestionIssuePayload(q, issueType, description, at) {
  const options = q && q.options && typeof q.options === 'object'
    ? Object.entries(q.options).map(([k, v]) => `${k}. ${v || ''}`)
    : [];
  const answer = q && q.answer && typeof q.answer === 'object' ? q.answer : {};
  return {
    bank: '408',
    source_uid: platformSourceUid(q) || `408:local::${questionKey(q)}`,
    course: q.course || getCurrentCourse() || '',
    chapter: q.chapter || '',
    question_id: q.id || '',
    page: q.page || null,
    issue_type: issueType,
    description,
    snapshot: {
      title: q.content || '',
      options,
      answer: answer.choice || '',
      explanation: answer.explanation || '',
      image_ref: typeof q.image_ref === 'string' ? q.image_ref : (q.image_ref && q.image_ref.cropped) || null,
      version: q.version || q.data_version || at,
    },
  };
}

async function submitQuestionIssueQueue(opts) {
  opts = opts || {};
  if (!issueQueue || !issueQueue.length || !isPlatformHost()) return {ok: 0, fail: issueQueue ? issueQueue.length : 0};
  const token = await ensurePlatformToken();
  if (!token) return {ok: 0, fail: issueQueue.length};
  const pending = issueQueue.slice();
  const keep = [];
  let ok = 0;
  for (const item of pending) {
    try {
      const headers = {'Content-Type': 'application/json'};
      if (typeof token === 'string') headers.Authorization = 'Bearer ' + token;
      const r = await fetch('/api/study-records/question-issues', {
        method: 'POST', credentials: 'include', headers, body: JSON.stringify(item),
      });
      if (r.ok) ok++;
      else keep.push(item);
    } catch (e) { keep.push(item); }
  }
  issueQueue = keep;
  saveIssueQueue();
  if (!opts.silent && ok) flashToast(`已提交 ${ok} 条纠错反馈`);
  return {ok, fail: keep.length};
}

function exportIssues() {
  const keys = Object.keys(issuesMap);
  if (!keys.length) return;
  const lines = ['# 题目纠错反馈', '', `生成时间：${new Date().toLocaleString()}`, ''];
  keys.forEach(k => {
    const q = allQuestions.find(x => questionKey(x) === k);
    const title = q ? `${displayId(q)} · ${q.chapter}` : k;
    lines.push(`## ${title}`);
    (issuesMap[k] || []).forEach(it => lines.push(`- [${it.at}] ${it.text}`));
    lines.push('');
  });
  downloadText(lines.join('\n'), `mathbank-issues-${new Date().toISOString().slice(0,10)}.md`);
}

function downloadText(text, filename) {
  const blob = new Blob([text], {type: 'text/markdown;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportNotesAsMarkdown() {
  const keys = Object.keys(notesMap);
  if (!keys.length) {
    alert('暂无笔记可导出');
    return;
  }
  // 按章节聚合
  const byChapter = new Map();
  keys.forEach(k => {
    const q = allQuestions.find(x => questionKey(x) === k);
    if (!q) return;
    const ch = q.chapter || '未分类';
    if (!byChapter.has(ch)) byChapter.set(ch, []);
    byChapter.get(ch).push(q);
  });
  const lines = ['# 我的 408 笔记', '', `生成时间：${new Date().toLocaleString()}`, ''];
  for (const [ch, qs] of byChapter.entries()) {
    lines.push(`## ${ch}`);
    qs.sort((a, b) => (a.page || 0) - (b.page || 0));
    qs.forEach(q => {
      lines.push(`### ${displayId(q)} · 第 ${q.page} 页`);
      if (q.content) lines.push('', '> ' + q.content.replace(/\n/g, '\n> '));
      lines.push('', '**笔记：**', '');
      lines.push(stripNoteImages(notesMap[questionKey(q)]));
      lines.push('');
    });
  }
  downloadText(lines.join('\n'), `mathbank-notes-${new Date().toISOString().slice(0,10)}.md`);
}

// 顶部轻提示
let toastTimer = null;
function flashToast(msg) {
  let el = document.getElementById('flashToast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'flashToast';
    el.className = 'flash-toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1800);
}

function updateDetailStatusButtons(q) {
  const favBtn = document.getElementById('detailFavoriteBtn');
  if (favBtn) {
    const fav = isFavorite(q);
    favBtn.classList.toggle('active', fav);
    favBtn.setAttribute('aria-label', fav ? '取消收藏' : '收藏');
  }
  const st = getMastery(q);
  MASTERY_STATUSES.forEach(m => {
    const btn = document.getElementById('detail' + m.key[0].toUpperCase() + m.key.slice(1) + 'Btn');
    if (!btn) return;
    btn.classList.toggle('active', st === m.key);
  });
}

function getCurrentDetailQuestion() {
  if (currentModalIndex >= 0 && currentModalIndex < filteredQuestions.length) {
    return filteredQuestions[currentModalIndex];
  }
  return currentModalQuestion;
}

function getActiveQuestion() {
  const detail = document.getElementById('detailModal');
  const practice = document.getElementById('practiceModal');
  if (detail && detail.classList.contains('active')) return getCurrentDetailQuestion();
  if (practice && practice.classList.contains('active') && practiceQueue[practiceIndex]) {
    return practiceQueue[practiceIndex];
  }
  return null;
}

function toggleDetailFavorite() {
  const q = getCurrentDetailQuestion();
  if (!q) return;
  toggleFavorite(q);
  updateDetailStatusButtons(q);
}

function setDetailMastery(status) {
  const q = getCurrentDetailQuestion();
  if (!q) return;
  setMastery(q, status);
  updateDetailStatusButtons(q);
}

/** 打开详情：支持 filteredQuestions 下标，或直接传题目对象 */
function openDetail(indexOrQ) {
  let q = null;
  let index = -1;
  if (indexOrQ && typeof indexOrQ === 'object') {
    q = indexOrQ;
    index = filteredQuestions.indexOf(q);
  } else {
    index = Number(indexOrQ);
    if (Number.isFinite(index) && index >= 0 && index < filteredQuestions.length) {
      q = filteredQuestions[index];
    }
  }
  if (!q) return;
  currentModalIndex = index;
  currentModalQuestion = q;
  renderModalContent(q);
  saveCursor(q);
  openModal('detailModal');
}

function closeModal() {
  closeModalById('detailModal');
  currentModalQuestion = null;
}

function prevQuestion() {
  if (currentModalIndex > 0) {
    currentModalIndex--;
    currentModalQuestion = filteredQuestions[currentModalIndex];
    renderModalContent(currentModalQuestion);
    saveCursor(currentModalQuestion);
    document.querySelector('#detailModal .modal-body').scrollTop = 0;
    return;
  }
  // 不在筛选列表中：在 allQuestions 中前后翻
  if (currentModalQuestion) {
    const aIdx = allQuestions.indexOf(currentModalQuestion);
    if (aIdx > 0) {
      currentModalQuestion = allQuestions[aIdx - 1];
      currentModalIndex = filteredQuestions.indexOf(currentModalQuestion);
      renderModalContent(currentModalQuestion);
      saveCursor(currentModalQuestion);
      document.querySelector('#detailModal .modal-body').scrollTop = 0;
    }
  }
}

function nextQuestion() {
  if (currentModalIndex >= 0 && currentModalIndex < filteredQuestions.length - 1) {
    currentModalIndex++;
    currentModalQuestion = filteredQuestions[currentModalIndex];
    renderModalContent(currentModalQuestion);
    saveCursor(currentModalQuestion);
    document.querySelector('#detailModal .modal-body').scrollTop = 0;
    return;
  }
  if (currentModalQuestion) {
    const aIdx = allQuestions.indexOf(currentModalQuestion);
    if (aIdx >= 0 && aIdx < allQuestions.length - 1) {
      currentModalQuestion = allQuestions[aIdx + 1];
      currentModalIndex = filteredQuestions.indexOf(currentModalQuestion);
      renderModalContent(currentModalQuestion);
      saveCursor(currentModalQuestion);
      document.querySelector('#detailModal .modal-body').scrollTop = 0;
    }
  }
}

function bankAssetQuery() {
  const ver = (typeof window !== 'undefined' && window.__BANK_DATA_VER__)
    ? String(window.__BANK_DATA_VER__)
    : '';
  return ver ? ('?v=' + ver) : '';
}

/** 题图路径：相对当前页，兼容 /banks/408/ 挂载与本地根路径 */
function resolveImageSrc(imageRef) {
  if (!imageRef) return '';
  const q = bankAssetQuery();
  if (imageRef.cropped) {
    const rel = String(imageRef.cropped).replace(/^\/+/, '');
    // 平台挂载下用绝对路径，避免相对路径在子路由失效
    if (typeof location !== 'undefined' && (location.pathname || '').indexOf('/banks/408') === 0) {
      return '/banks/408/' + rel + q;
    }
    return rel + q;
  }
  const page = String(imageRef.page).padStart(3, '0');
  if (typeof location !== 'undefined' && (location.pathname || '').indexOf('/banks/408') === 0) {
    return `/banks/408/../pdf_images/page_${page}.png` + q;
  }
  return `../pdf_images/page_${page}.png` + q;
}

function appendExplainImage(el, path) {
  const src = resolveImageSrc({ cropped: path });
  if (!src) return;
  const fig = document.createElement('figure');
  fig.className = 'q-image q-image-inline';
  const img = document.createElement('img');
  img.src = src;
  img.alt = '解析配图';
  img.loading = 'eager';
  img.decoding = 'async';
  img.addEventListener('click', () => zoomImage(img.src));
  img.addEventListener('error', () => fig.classList.add('is-broken'));
  fig.appendChild(img);
  el.appendChild(fig);
}

/** 答案区截图已是原书解析，OCR 正文与图重复；有答案图时不再渲文字。题目配图不触发。 */
function shouldHideExplanationProse(expl) {
  return /(?:答案图片|解析图片|答图)\s*[：:]\s*\S+?\.(?:png|jpe?g|webp|gif)/i.test(String(expl || ''));
}

function fillExplanation(el, expl, prefix) {
  if (!el) return;
  const raw = String(expl || '');
  if (!raw.trim()) {
    el.textContent = prefix || '';
    return;
  }
  const hideProse = shouldHideExplanationProse(raw);
  const assetRe = /(?:题目图片|答案图片|解析图片|题图|答图)\s*[：:]\s*(\S+?\.(?:png|jpe?g|webp|gif))/gi;
  const chunks = [];
  let last = 0;
  let m;
  while ((m = assetRe.exec(raw)) !== null) {
    if (m.index > last) chunks.push({ type: 'text', value: raw.slice(last, m.index) });
    chunks.push({ type: 'img', path: String(m[1]).replace(/[.,;，。；]+$/, '') });
    last = m.index + m[0].length;
  }
  if (last < raw.length) chunks.push({ type: 'text', value: raw.slice(last) });
  el.replaceChildren();
  let started = false;
  for (const chunk of chunks) {
    if (chunk.type === 'img') {
      appendExplainImage(el, chunk.path);
      continue;
    }
    if (hideProse) continue;
    const piece = (!started && prefix ? prefix : '') + prepareMathText(chunk.value);
    started = true;
    if (!piece.trim()) continue;
    const wrap = document.createElement('div');
    wrap.textContent = piece.trim();
    renderKatex(wrap);
    el.appendChild(wrap);
  }
}

function imageHtml(imageRef) {
  if (!imageRef) return '';
  const imgPath = resolveImageSrc(imageRef);
  if (!imgPath) return '';
  const pageLabel = imageRef.page != null && imageRef.page !== ''
    ? `第 ${imageRef.page} 页`
    : '题目配图';
  // 默认直接展开配图：题干「如下图」时打开即见，无需点击「查看原图」
  return `
    <figure class="q-image q-image-inline" data-role="qimage">
      <img src="${imgPath}" alt="${escapeHtml(pageLabel)}" loading="eager" decoding="async"
        onerror="this.closest('.q-image').classList.add('is-broken')"
        onclick="zoomImage(this.src)">
      <figcaption class="q-image-note">题目配图 · ${escapeHtml(pageLabel)} <span class="q-image-hint">（点击放大）</span></figcaption>
    </figure>
  `;
}

function zoomImage(src) {
  const overlay = document.createElement('div');
  overlay.className = 'zoom-overlay';
  const img = document.createElement('img');
  img.src = src;
  img.draggable = false;
  let scale = 1, tx = 0, ty = 0;
  let dragging = false, startX = 0, startY = 0;
  function apply() {
    img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
  }
  overlay.appendChild(img);
  overlay.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    scale = Math.min(8, Math.max(1, scale * delta));
    if (scale === 1) { tx = 0; ty = 0; }
    apply();
  }, {passive: false});
  img.addEventListener('mousedown', (e) => {
    if (scale <= 1) return;
    dragging = true;
    startX = e.clientX - tx;
    startY = e.clientY - ty;
    img.style.cursor = 'grabbing';
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    tx = e.clientX - startX;
    ty = e.clientY - startY;
    apply();
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    img.style.cursor = 'grab';
  });
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove();
  });
  document.body.appendChild(overlay);
  img.style.cursor = 'grab';
}

function openHelp() { openModal('helpModal'); }
function closeHelp() { closeModalById('helpModal'); }
function openDashboard() { renderDashboard(); openModal('dashboardModal'); }
function closeDashboard() { closeModalById('dashboardModal'); }

// ========================
// 相似题推荐（基于 searchTokens 重叠度）
// ========================
function findSimilarQuestions(q, topN) {
  topN = topN || 5;
  const qKey = questionKey(q);
  const qTokens = q._searchTokens;
  if (!qTokens || qTokens.size === 0) return [];
  const candidates = [];
  for (const other of allQuestions) {
    if (questionKey(other) === qKey) continue;
    if (!other._searchTokens) continue;
    // 简单 Jaccard：交集 / 并集
    let inter = 0;
    qTokens.forEach(t => { if (other._searchTokens.has(t)) inter++; });
    if (inter === 0) continue;
    const union = qTokens.size + other._searchTokens.size - inter;
    const score = inter / union;
    // 同章节加权
    const sameChapter = (q.chapterKey || '') === (other.chapterKey || '') ? 0.2 : 0;
    candidates.push({q: other, score: score + sameChapter, inter});
  }
  candidates.sort((a, b) => b.score - a.score || b.inter - a.inter);
  return candidates.slice(0, topN).map(c => c.q);
}

// ========================
// 试卷生成
// ========================
let currentPaper = null;
function openPaper() {
  // 加载课程下拉
  const sel = document.getElementById('paperCourse');
  sel.innerHTML = '';
  getAvailableCourses().forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = c.short || c.name;
    if (c.name === getCurrentCourse()) opt.selected = true;
    sel.appendChild(opt);
  });
  updatePaperChapters();
  generatePaper();
  openModal('paperModal');
}
function closePaper() { closeModalById('paperModal'); }
function updatePaperChapters() {
  const courseName = document.getElementById('paperCourse').value;
  const chSel = document.getElementById('paperChapter');
  chSel.innerHTML = '<option value="">全部章节</option>';
  currentChapters
    .filter(ch => (ch.course || (bank && bank.courses && bank.courses[0] ? bank.courses[0].name : '')) === courseName || courseName === getCurrentCourse())
    .filter(ch => (ch.question_count || (ch.questions && ch.questions.length) || 0) > 0)
    .filter(ch => {
      if (!CHOICE_ONLY_MODE) return true;
      const sec = ch.section_type || '';
      if (sec && String(sec).includes('解答')) return false;
      if (sec && !isChoiceQuestionType(sec) && !String(sec).includes('选择')) return false;
      return true;
    })
    .forEach(ch => {
      const opt = document.createElement('option');
      opt.value = ch.name;
      opt.textContent = ch.name + ' (' + ch.question_count + ')';
      chSel.appendChild(opt);
    });
  // 试卷题型下拉：仅可见题型
  const typeSel = document.getElementById('paperType');
  if (typeSel && _COV) {
    const types = {};
    allQuestions.forEach(q => { types[q.type] = (types[q.type] || 0) + 1; });
    const items = _COV.buildTypeStatItems(types);
    const prev = typeSel.value;
    typeSel.innerHTML = '';
    const any = document.createElement('option');
    any.value = '';
    any.textContent = '不限';
    typeSel.appendChild(any);
    items.forEach(function(it) {
      const opt = document.createElement('option');
      opt.value = it.action;
      opt.textContent = '仅' + it.action;
      typeSel.appendChild(opt);
    });
    if (prev && types[prev]) typeSel.value = prev;
    else typeSel.value = '';
  }
}
function generatePaper() {
  const courseName = document.getElementById('paperCourse').value;
  const chapter = document.getElementById('paperChapter').value;
  const type = document.getElementById('paperType').value;
  const count = Math.max(1, Math.min(200, parseInt(document.getElementById('paperCount').value) || 20));
  const shuffle = document.getElementById('paperShuffle').checked;
  let pool = allQuestions.filter(q => (q.course || getCurrentCourse()) === courseName);
  if (chapter) pool = pool.filter(q => q.chapter === chapter);
  if (type) pool = pool.filter(q => q.type === type);
  if (shuffle) pool = shuffleArray([...pool]);
  currentPaper = pool.slice(0, count);
  // 渲染预览
  const prev = document.getElementById('paperPreview');
  if (currentPaper.length === 0) {
    prev.innerHTML = '<p style="color:var(--text-tertiary);text-align:center;padding:20px">当前条件下没有题目</p>';
    return;
  }
  prev.innerHTML = `<h3>试卷预览（${currentPaper.length} 道）</h3>` +
    currentPaper.map((q, i) => {
      const opts = q.options ? sortedOptionEntries(q.options).map(([k, v]) => `<div>${k}. ${escapeHtml(v)}</div>`).join('') : '';
      const subs = q.sub_questions ? q.sub_questions.map((s, j) => `<div>(${j+1}) ${escapeHtml(s)}</div>`).join('') : '';
      return `<div class="paper-q"><strong>${i+1}. (${escapeHtml(displayId(q))} · ${escapeHtml(q.type)} · 第 ${q.page} 页)</strong><div>${escapeHtml(q.content || '')}</div>${opts ? '<div style="margin-top:6px">' + opts + '</div>' : ''}${subs ? '<div style="margin-top:6px">' + subs + '</div>' : ''}<div style="margin-top:8px;height:1.4em"></div></div>`;
    }).join('');
}
function buildPaperMarkdown(includeAnswer) {
  if (!currentPaper || !currentPaper.length) return '';
  const title = '王道 408 真题精选试卷';
  const date = new Date().toLocaleDateString();
  const lines = [`# ${title}`, '', `日期：${date}　|　题量：${currentPaper.length}　|　科目：${document.getElementById('paperCourse').value}`, '', '---', '', '姓名：_____________　　学号：_____________　　得分：_____________', ''];
  currentPaper.forEach((q, i) => {
    lines.push(`## ${i+1}. （${displayId(q)} · ${q.type} · 第 ${q.page} 页）`);
    if (q.content) lines.push('', q.content);
    if (q.options) {
      lines.push('');
      for (const [k, v] of sortedOptionEntries(q.options)) lines.push(`- **${k}**. ${v}`);
    }
    if (q.sub_questions) {
      lines.push('', '子问题：');
      q.sub_questions.forEach((s, j) => lines.push(`${j+1}. ${s}`));
    }
    if (includeAnswer) {
      lines.push('');
      if (q.answer && q.answer.choice) lines.push(`> ✅ 答案：${q.answer.choice}`);
      if (q.answer && q.answer.explanation) lines.push(`> 解析：${q.answer.explanation}`);
    } else {
      lines.push('', '**作答：** ______________________________________');
    }
    lines.push('', '');
  });
  return lines.join('\n');
}
function downloadPaper() {
  if (!currentPaper || !currentPaper.length) { alert('请先生成试卷'); return; }
  downloadText(buildPaperMarkdown(false), `mathbank-paper-${new Date().toISOString().slice(0,10)}.md`);
}
function downloadAnswerSheet() {
  if (!currentPaper || !currentPaper.length) { alert('请先生成试卷'); return; }
  downloadText(buildPaperMarkdown(true), `mathbank-paper-answers-${new Date().toISOString().slice(0,10)}.md`);
}
function printPaper() {
  if (!currentPaper || !currentPaper.length) { alert('请先生成试卷'); return; }
  // 简单实现：弹一个新窗口供打印
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>试卷</title>
  <style>body{font-family:"Microsoft YaHei",serif;max-width:720px;margin:30px auto;padding:0 20px;line-height:1.7;color:#222}
  h1{text-align:center}h2{margin-top:24px}.paper-q{margin-bottom:18px;page-break-inside:avoid}
  .opts{margin:6px 0}@media print{body{margin:0}}</style></head><body>
  ${document.getElementById('paperPreview').innerHTML}
  <script>setTimeout(()=>window.print(),200)</script>
  </body></html>`;
  const w = window.open('', '_blank');
  w.document.write(html);
  w.document.close();
}

// ========================
// 错题本
// ========================
function openWrongBook() { renderWrongBook(); openModal('wrongBookModal'); }
function closeWrongBook() { closeModalById('wrongBookModal'); }

function wrongBookStats() {
  // 统计每道题：错题次数 / 上次错时间
  const map = new Map();
  for (const e of wrongLog) {
    if (!map.has(e.key)) map.set(e.key, {count: 0, lastAt: 0, firstAt: Infinity, chapter: e.chapter, qid: e.qid, type: e.type, page: e.page, correctAnswer: e.correctAnswer});
    const v = map.get(e.key);
    v.count++;
    v.lastAt = Math.max(v.lastAt, e.at);
    v.firstAt = Math.min(v.firstAt, e.at);
  }
  return map;
}

function renderWrongBook() {
  const stats = wrongBookStats();
  if (stats.size === 0) {
    document.getElementById('wrongBookContent').innerHTML = `
      <div class="empty-state">
        <h3>暂无错题</h3>
        <p>去练习模式做几道题，错题会自动汇总到这里</p>
      </div>`;
    return;
  }
  const groupBy = document.getElementById('wrongBookGroupBy').value;
  // 把 Map 转成数组并按规则排序
  let arr = Array.from(stats.entries()).map(([key, v]) => ({key, ...v}));
  arr.sort((a, b) => b.lastAt - a.lastAt);

  let html = '';
  if (groupBy === 'chapter') {
    const byCh = new Map();
    arr.forEach(it => {
      const ch = it.chapter || '未分类';
      if (!byCh.has(ch)) byCh.set(ch, []);
      byCh.get(ch).push(it);
    });
    for (const [ch, items] of byCh.entries()) {
      html += `<h4>${escapeHtml(ch)} <span style="color:var(--text-tertiary);font-size:0.78rem;font-weight:400">（${items.length} 道）</span></h4>`;
      html += items.map(it => wrongBookItemHtml(it)).join('');
    }
  } else {
    // 按时间分：今天 / 昨天 / 本周 / 更早
    const now = Date.now();
    const todayStart = new Date(); todayStart.setHours(0,0,0,0);
    const yesterday = todayStart.getTime() - 86400000;
    const weekAgo = todayStart.getTime() - 7 * 86400000;
    const groups = {今日: [], 昨日: [], 本周: [], 更早: []};
    arr.forEach(it => {
      if (it.lastAt >= todayStart.getTime()) groups['今日'].push(it);
      else if (it.lastAt >= yesterday) groups['昨日'].push(it);
      else if (it.lastAt >= weekAgo) groups['本周'].push(it);
      else groups['更早'].push(it);
    });
    for (const [k, items] of Object.entries(groups)) {
      if (!items.length) continue;
      html += `<h4>${k} <span style="color:var(--text-tertiary);font-size:0.78rem;font-weight:400">（${items.length} 道）</span></h4>`;
      html += items.map(it => wrongBookItemHtml(it)).join('');
    }
  }
  document.getElementById('wrongBookContent').innerHTML = `
    <div class="wrongbook-summary">共 <strong>${stats.size}</strong> 道错题，累计 <strong>${wrongLog.length}</strong> 次答错</div>
    ${html}
  `;
  // 绑定点击跳转
  document.querySelectorAll('.wrongbook-item').forEach(el => {
    el.addEventListener('click', () => {
      const q = allQuestions.find(x => questionKey(x) === el.dataset.key);
      if (!q) {
        flashToast('该题不在当前课程，请先切换到对应科目');
        return;
      }
      closeWrongBook();
      openDetail(q);
    });
  });
}

function wrongBookItemHtml(it) {
  const q = allQuestions.find(x => questionKey(x) === it.key);
  const preview = q ? (q.content ? q.content.slice(0, 60) : (q.sub_questions && q.sub_questions[0] || '（无题干）')) : '（题目已不在当前课程）';
  const last = new Date(it.lastAt);
  const dateStr = `${last.getMonth()+1}/${last.getDate()}`;
  return `
    <div class="wrongbook-item" data-key="${escapeHtml(it.key)}" data-index="${allQuestions.indexOf(q)}">
      <div class="wb-main">
        <div class="wb-id">${escapeHtml(it.qid || '')} · ${escapeHtml(it.type || '')} · 第 ${it.page} 页</div>
        <div class="wb-text">${escapeHtml(preview).replace(/\$([^$]+)\$/g, '$1')}</div>
        <div class="wb-meta">${escapeHtml(it.chapter || '')}${it.correctAnswer ? ' · 答案：<span style="color:var(--accent)">' + escapeHtml(it.correctAnswer) + '</span>' : ''}</div>
      </div>
      <div class="wb-stats">
        <div class="wb-count" title="错题次数">${it.count}×</div>
        <div class="wb-date">${dateStr}</div>
      </div>
    </div>
  `;
}

function exportWrongBook() {
  const stats = wrongBookStats();
  if (stats.size === 0) {
    alert('暂无错题可导出');
    return;
  }
  // 按章节聚合
  const byCh = new Map();
  for (const [key, v] of stats.entries()) {
    const ch = v.chapter || '未分类';
    if (!byCh.has(ch)) byCh.set(ch, []);
    byCh.get(ch).push({key, ...v});
  }
  const lines = ['# 我的 408 错题本', '', `生成时间：${new Date().toLocaleString()}`, '', `总计 ${stats.size} 道错题，累计 ${wrongLog.length} 次答错`, ''];
  for (const [ch, items] of byCh.entries()) {
    lines.push(`## ${ch}`);
    lines.push('');
    items.sort((a, b) => b.count - a.count);
    for (const it of items) {
      const q = allQuestions.find(x => questionKey(x) === it.key);
      lines.push(`### ${it.qid || ''} · 第 ${it.page} 页 · ${it.type || ''}`);
      if (q && q.content) lines.push('', '> ' + q.content.replace(/\n/g, '\n> '));
      if (q && q.options) {
        lines.push('');
        for (const [k, v] of sortedOptionEntries(q.options)) lines.push(`- **${k}**. ${v}`);
      }
      if (q && q.answer && q.answer.choice) lines.push('', `**答案**：${q.answer.choice}`);
      if (q && q.answer && q.answer.explanation) lines.push(`**解析**：${q.answer.explanation}`);
      lines.push('', `> ❌ 错题次数：${it.count}　|　上次：${new Date(it.lastAt).toLocaleString()}`);
      const note = notesMap[it.key];
      if (note) lines.push('', `> 📝 笔记：${stripNoteImages(note)}`);
      lines.push('', '---', '');
    }
  }
  downloadText(lines.join('\n'), `mathbank-wrongbook-${new Date().toISOString().slice(0,10)}.md`);
}

// 学习仪表盘：基于 attemptLog 统计做题；review 仅作复习参考
function renderDashboard() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const todayTs = today.getTime();
  const dayMs = 86400000;
  const dayKey = (ts) => {
    const d = new Date(ts);
    d.setHours(0, 0, 0, 0);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  };

  // 按自然日聚合 attemptLog（最近 60 天用于 streak，最近 7 天用于图表）
  const dailyDone = {}; // YYYY-MM-DD → {done, wrong, correct}
  for (let i = 0; i < 60; i++) {
    dailyDone[dayKey(todayTs - i * dayMs)] = { done: 0, wrong: 0, correct: 0 };
  }
  let totalDone = 0, totalCorrect = 0;
  const courseStats = {};
  attemptLog.forEach(a => {
    if (!a || !a.at) return;
    const k = dayKey(a.at);
    totalDone++;
    if (a.isCorrect) totalCorrect++;
    if (dailyDone[k]) {
      dailyDone[k].done++;
      if (a.isCorrect) dailyDone[k].correct++;
      else dailyDone[k].wrong++;
    }
    const c = a.course || '未知';
    if (!courseStats[c]) courseStats[c] = { done: 0, correct: 0 };
    courseStats[c].done++;
    if (a.isCorrect) courseStats[c].correct++;
  });

  const todayKey = dayKey(todayTs);
  const todayStats = dailyDone[todayKey] || { done: 0, wrong: 0, correct: 0 };
  const overallRate = totalDone ? Math.round(totalCorrect / totalDone * 100) : 0;

  // Streak：从今天往前，允许今天为 0 不打断
  let streak = 0;
  for (let i = 0; i < 60; i++) {
    const k = dayKey(todayTs - i * dayMs);
    const n = (dailyDone[k] && dailyDone[k].done) || 0;
    if (n > 0) streak++;
    else if (i === 0) continue;
    else break;
  }

  // 7 天趋势
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const ts = todayTs - i * dayMs;
    const d = new Date(ts);
    const k = dayKey(ts);
    const s = dailyDone[k] || { done: 0, wrong: 0 };
    days.push({ k, label: (d.getMonth() + 1) + '/' + d.getDate(), done: s.done, wrong: s.wrong });
  }
  const maxBar = Math.max(1, ...days.map(d => d.done));
  const barW = 50, gap = 14, baseY = 130, chartH = 110;
  const chartW = days.length * (barW + gap) + 20;
  let svg = `<svg viewBox="0 0 ${chartW} ${baseY + 20}" width="100%" style="max-width:${chartW}px;display:block">`;
  days.forEach((d, i) => {
    const x = 10 + i * (barW + gap);
    const h = Math.round((d.done / maxBar) * chartH);
    const wrongH = Math.round((d.wrong / Math.max(1, d.done)) * h);
    const y = baseY - h;
    svg += `<rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="4" fill="var(--text-primary)" opacity="${d.done ? 0.75 : 0.12}"/>`;
    if (wrongH > 0) {
      svg += `<rect x="${x}" y="${y}" width="${barW}" height="${wrongH}" rx="4" fill="var(--danger)"/>`;
    }
    svg += `<text x="${x + barW / 2}" y="${baseY + 14}" text-anchor="middle" font-size="10" fill="var(--text-tertiary)">${d.label}</text>`;
    if (d.done) svg += `<text x="${x + barW / 2}" y="${y - 4}" text-anchor="middle" font-size="10" font-weight="600" fill="var(--text-primary)">${d.done}</text>`;
  });
  svg += `</svg>`;

  const courseEntries = Object.entries(courseStats).filter(([_, v]) => v.done > 0)
    .sort((a, b) => b[1].done - a[1].done);
  let courseHtml = '';
  if (courseEntries.length) {
    const maxCourse = Math.max(1, ...courseEntries.map(([_, v]) => v.done));
    courseHtml = courseEntries.map(([name, v]) => {
      const rate = v.done ? Math.round(v.correct / v.done * 100) : 0;
      const w = Math.round((v.done / maxCourse) * 200);
      const color = rate >= 80 ? 'var(--success)' : rate >= 60 ? 'var(--warning)' : 'var(--danger)';
      return `<div class="course-row">
        <div class="course-name">${escapeHtml(name)}</div>
        <div class="course-bar"><div class="course-bar-fill" style="width:${w}px;background:${color}"></div></div>
        <div class="course-meta">${v.done} 题 · ${rate}%</div>
      </div>`;
    }).join('');
  } else {
    courseHtml = '<p style="color:var(--text-tertiary);font-size:0.88rem">还没有做题数据，去做几道试试吧</p>';
  }

  const due = dueCount();
  let masteredCount = 0;
  Object.values(statusMap).forEach(v => {
    if (normalizeStatusEntry(v).mastery === 'mastered') masteredCount++;
  });

  document.getElementById('dashboardContent').innerHTML = `
    <div class="dash-grid">
      <div class="dash-card"><div class="dash-label">今日做题</div><div class="dash-value">${todayStats.done}</div></div>
      <div class="dash-card"><div class="dash-label">今日错题</div><div class="dash-value" style="color:var(--danger)">${todayStats.wrong}</div></div>
      <div class="dash-card"><div class="dash-label">累计正确率</div><div class="dash-value">${overallRate}%</div></div>
      <div class="dash-card"><div class="dash-label">连续打卡</div><div class="dash-value">${streak}<small>天</small></div></div>
      <div class="dash-card"><div class="dash-label">待复习</div><div class="dash-value">${due}</div></div>
      <div class="dash-card"><div class="dash-label">已掌握</div><div class="dash-value">${masteredCount}</div></div>
    </div>
    <h4>最近 7 天</h4>
    ${svg}
    <p style="font-size:0.78rem;color:var(--text-tertiary);margin-top:4px">深色柱=作答次数 · 红色=其中错误次数（基于答题记录）</p>
    <h4>各科正确率</h4>
    ${courseHtml}
  `;
}

// ========================
// Practice Mode
// ========================
/** 把某课程 JSON 展平成可练习的题目列表（含 chapter / course） */
function flattenCourseQuestions(courseData, courseName) {
  const out = [];
  if (!courseData || !courseData.chapters) return out;
  const tokenSplitRe = /[\s,.;:!?。，；：！？、（）()\[\]"'"]+/;
  courseData.chapters.forEach(ch => {
    const chapterKey = (ch.l1_name || '?') + '|' + (ch.l2_name || '?') + '|' + (ch.section_type || '?');
    (ch.questions || []).forEach(q => {
      const entry = { ...q, chapter: ch.name, chapterKey, course: ch.course || courseName || '' };
      const parts = [entry.content || '', entry.chapter || '', entry.id || ''];
      if (entry.options) Object.values(entry.options).forEach(v => parts.push(v));
      if (entry.sub_questions) entry.sub_questions.forEach(s => parts.push(s));
      if (entry.answer) {
        if (entry.answer.choice) parts.push(entry.answer.choice);
        if (entry.answer.explanation) parts.push(entry.answer.explanation);
      }
      entry._searchText = parts.join(' ').toLowerCase();
      const tokens = new Set();
      entry._searchText.split(tokenSplitRe).forEach(t => { if (t.length > 1) tokens.add(t); });
      entry._searchTokens = tokens;
      if (qualityVisible(entry)) out.push(entry);
    });
  });
  return out;
}

async function loadMixedPool(count) {
  const courses = getAvailableCourses();
  const pools = await Promise.all(courses.map(async c => {
    try {
      const data = await window.loadCourseData(c.name);
      return flattenCourseQuestions(data, c.name);
    } catch (e) {
      console.warn('mixed load failed', c.name, e);
      return [];
    }
  }));
  const merged = pools.flat();
  // 按科目尽量均衡抽样
  const byCourse = new Map();
  merged.forEach(q => {
    const c = q.course || '未知';
    if (!byCourse.has(c)) byCourse.set(c, []);
    byCourse.get(c).push(q);
  });
  byCourse.forEach((arr, k) => byCourse.set(k, shuffleArray(arr)));
  const per = Math.max(1, Math.floor(count / Math.max(1, byCourse.size)));
  let picked = [];
  byCourse.forEach(arr => { picked = picked.concat(arr.slice(0, per)); });
  if (picked.length < count) {
    const rest = shuffleArray(merged.filter(q => !picked.includes(q)));
    picked = picked.concat(rest.slice(0, count - picked.length));
  }
  return shuffleArray(picked).slice(0, count);
}

async function startPractice(status) {
  const saved = loadProgress();
  if (saved && saved.ids && saved.ids.length > 0) {
    const choice = confirm(`发现上次未完成的练习（${saved.ids.length} 道题，进度 ${saved.index + 1}/${saved.ids.length}）。\n\n确定 = 继续上次练习\n取消 = 开始新练习`);
    if (choice) {
      if (await resumePractice(saved)) return;
    } else {
      clearProgress();
    }
  }

  // 解析考试模式：timed30 / timed60 / target50 / mixed80
  practiceMode = null;
  practiceDeadline = 0;
  if (status === 'timed30') { practiceMode = 'timed'; practiceDeadline = Date.now() + 30 * 60 * 1000; }
  else if (status === 'timed60') { practiceMode = 'timed'; practiceDeadline = Date.now() + 60 * 60 * 1000; }
  else if (status === 'target50') { practiceMode = 'target'; }
  else if (status === 'mixed80') { practiceMode = 'mixed'; }

  let pool;
  if (status === 'review') {
    pool = getDueQuestions();
  } else if (practiceMode === 'mixed') {
    flashToast('正在加载四科题目…');
    pool = await loadMixedPool(80);
  } else if (practiceMode === 'target') {
    const type = document.getElementById('typeFilter').value;
    const feature = document.getElementById('featureFilter').value;
    pool = filterQuestions(allQuestions, { chapter: selectedChapter, type, feature });
  } else {
    const type = document.getElementById('typeFilter').value;
    const feature = document.getElementById('featureFilter').value;
    // status 可能是 unknown/favorite 等练习入口，或 timed 模式
    const statusFilter = (status && !['timed30', 'timed60', 'target50', 'mixed80', 'review', 'current'].includes(status))
      ? status
      : activeStatusFilter;
    pool = filterQuestions(allQuestions, { chapter: selectedChapter, type, feature, status: statusFilter });
  }

  if (pool.length === 0) {
    const statusMsgs = {
      wrong: '还没有错题，先去练习吧',
      favorite: '还没有收藏题目',
      unknown: '还没有标记为「不会」的题目',
      familiar: '还没有标记为「不熟」的题目',
      unmarked: '当前筛选下没有未标记的题目',
      review: '今天没有需要复习的题目，先去刷题吧',
      timed30: '当前筛选下没有题目，无法开始限时练习',
      timed60: '当前筛选下没有题目，无法开始限时练习',
      target50: '当前筛选下没有题目',
      mixed80: '跨科题目加载失败或为空'
    };
    const msg = statusMsgs[status] || '当前筛选条件下没有题目，请先调整筛选条件';
    alert(msg);
    return;
  }

  practiceQueue = shuffleArray([...pool]);
  if (practiceMode === 'target') practiceQueue = practiceQueue.slice(0, 50);
  if (practiceMode === 'mixed') practiceQueue = practiceQueue.slice(0, 80);
  practiceIndex = 0;
  practiceResults = [];
  practiceFinished = false;
  setPracticeFooter(true);
  saveProgress();
  renderPractice();
  openModal('practiceModal');

  stopPracticeTimer();
  if (practiceMode === 'timed') startPracticeTimer();
}

function setPracticeFooter(visible) {
  const footer = document.querySelector('#practiceModal .modal-footer');
  if (footer) footer.style.display = visible ? 'flex' : 'none';
}

function renderPractice() {
  const q = practiceQueue[practiceIndex];
  const container = document.getElementById('practiceContent');
  const progress = `${practiceIndex + 1} / ${practiceQueue.length}`;

  let timerHtml = '';
  if (practiceMode === 'timed') {
    timerHtml = `<div class="practice-timer" id="practiceTimer"><span class="practice-timer-label">⏱ 剩余时间</span><span class="practice-timer-value" id="practiceTimerValue">--:--</span></div>`;
  }

  container.innerHTML = `
    ${timerHtml}
    <div class="practice-progress">${escapeHtml(q.chapter)} · ${escapeHtml(displayId(q))} · ${progress}</div>
    <div class="practice-question">
      <div class="q-id" style="margin-bottom:14px;font-size:0.95rem;color:var(--text-tertiary);font-weight:600;">${q.type} · 第 ${q.page} 页</div>
      ${questionBodyHtml(q, 'practice')}
    </div>
  `;

  renderQuestionBody(container, q, 'practice');
  restorePracticeState(container, q);
  if (practiceMode === 'timed') updateTimerDisplay();
  saveProgress();
}

// 倒计时相关
function startPracticeTimer() {
  practiceTimer = setInterval(() => {
    updateTimerDisplay();
    if (Date.now() >= practiceDeadline) {
      stopPracticeTimer();
      alert('⏰ 时间到，自动交卷！');
      finishPractice();
    }
  }, 1000);
}
function stopPracticeTimer() {
  if (practiceTimer) { clearInterval(practiceTimer); practiceTimer = null; }
}
function updateTimerDisplay() {
  const el = document.getElementById('practiceTimerValue');
  const box = document.getElementById('practiceTimer');
  if (!el || !box) return;
  const remain = Math.max(0, practiceDeadline - Date.now());
  const m = Math.floor(remain / 60000);
  const s = Math.floor((remain % 60000) / 1000);
  el.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  box.classList.toggle('warn', remain < 5 * 60 * 1000);
}

function nextPractice() {
  if (practiceIndex < practiceQueue.length - 1) {
    practiceIndex++;
    renderPractice();
  } else {
    finishPractice();
  }
  // 限时模式：到点自动交卷
  if (practiceMode === 'timed' && Date.now() >= practiceDeadline) {
    stopPracticeTimer();
    alert('⏰ 时间到，自动交卷！');
    finishPractice();
  }
}

function finishPractice() {
  practiceFinished = true;
  stopPracticeTimer();
  practiceMode = null;
  clearProgress();
  const answered = practiceResults.length;
  const correct = practiceResults.filter(r => r.correct).length;
  const wrong = answered - correct;
  const rate = answered ? Math.round(correct / answered * 100) : 0;
  const skipped = Math.max(0, practiceQueue.length - answered);

  const container = document.getElementById('practiceContent');
  container.innerHTML = `
    <div class="practice-summary">
      <h2>练习完成</h2>
      <div class="summary-stats">
        <div class="summary-item"><span>${practiceQueue.length}</span><label>队列题数</label></div>
        <div class="summary-item"><span>${answered}</span><label>已作答</label></div>
        <div class="summary-item correct"><span>${correct}</span><label>正确</label></div>
        <div class="summary-item wrong"><span>${wrong}</span><label>错误</label></div>
      </div>
      <p style="color:var(--text-tertiary);font-size:0.85rem;margin:8px 0 18px">
        正确率 <strong style="color:var(--text-primary)">${rate}%</strong>
        ${skipped ? ` · 跳过 ${skipped} 题` : ''}
        （按已作答题计算）
      </p>
      <div class="summary-actions">
        <button class="btn btn-primary" onclick="restartPractice()">重新练习</button>
        <button class="btn btn-secondary" onclick="closePractice()">退出</button>
      </div>
    </div>
  `;
  setPracticeFooter(false);
}

function restartPractice() {
  practiceQueue = shuffleArray([...practiceQueue]);
  practiceIndex = 0;
  practiceResults = [];
  practiceFinished = false;
  setPracticeFooter(true);
  saveProgress();
  renderPractice();
}

function closePractice() {
  stopPracticeTimer();
  // 未完成时保留进度，便于下次续做；已完成则已 clearProgress
  if (!practiceFinished) saveProgress();
  closeModalById('practiceModal');
}

function prevPractice() {
  if (practiceFinished) return;
  if (practiceIndex > 0) {
    practiceIndex--;
    renderPractice();
  }
}

async function resumePractice(saved) {
  // 尽量从缓存/当前课恢复；跨科进度需加载各科
  let idMap = new Map(allQuestions.map(q => [questionKey(q), q]));
  const missing = (saved.ids || []).filter(k => !idMap.has(k));
  if (missing.length && window.loadCourseData) {
    try {
      const courses = getAvailableCourses();
      for (const c of courses) {
        const data = await window.loadCourseData(c.name);
        flattenCourseQuestions(data, c.name).forEach(q => idMap.set(questionKey(q), q));
      }
    } catch (e) { console.warn(e); }
  }
  practiceQueue = (saved.ids || []).map(k => idMap.get(k)).filter(Boolean);
  if (practiceQueue.length === 0) return false;
  practiceIndex = Math.min(saved.index || 0, practiceQueue.length - 1);
  // 恢复已作答结果
  practiceResults = [];
  if (Array.isArray(saved.results)) {
    saved.results.forEach(r => {
      const q = idMap.get(r.key);
      if (q) practiceResults.push({ q, correct: !!r.correct });
    });
  }
  practiceFinished = false;
  practiceMode = saved.mode || null;
  practiceDeadline = saved.deadline || 0;
  // 限时：若已过期则直接交卷；否则续跑
  stopPracticeTimer();
  if (practiceMode === 'timed') {
    if (practiceDeadline && Date.now() >= practiceDeadline) {
      openModal('practiceModal');
      finishPractice();
      return true;
    }
    if (!practiceDeadline) practiceDeadline = Date.now() + 30 * 60 * 1000;
    startPracticeTimer();
  }
  setPracticeFooter(true);
  renderPractice();
  openModal('practiceModal');
  return true;
}

function practiceKey() {
  return 'mathbank_practice_progress_v2';
}
function saveProgress() {
  if (practiceFinished || !practiceQueue.length) return;
  const payload = {
    version: 2,
    ids: practiceQueue.map(questionKey),
    index: practiceIndex,
    results: practiceResults.map(r => ({ key: questionKey(r.q), correct: !!r.correct })),
    mode: practiceMode,
    deadline: practiceDeadline || 0,
    savedAt: Date.now()
  };
  safeSetItem(practiceKey(), JSON.stringify(payload));
  // 清理旧键
  try { localStorage.removeItem('mathbank_practice_progress_v1'); } catch (e) {}
}
function loadProgress() {
  try {
    let r = localStorage.getItem(practiceKey());
    if (!r) r = localStorage.getItem('mathbank_practice_progress_v1');
    return r ? JSON.parse(r) : null;
  } catch (e) { return null; }
}
function clearProgress() {
  try {
    localStorage.removeItem(practiceKey());
    localStorage.removeItem('mathbank_practice_progress_v1');
  } catch (e) {}
}

function randomQuestion() {
  if (filteredQuestions.length === 0) return;
  const tiers = [[], [], [], []];
  filteredQuestions.forEach((q, i) => {
    const st = getMastery(q);
    if (st === 'unknown') tiers[0].push(i);
    else if (st === 'familiar') tiers[1].push(i);
    else if (!st) tiers[2].push(i);
    else tiers[3].push(i);
  });
  const pool = tiers.find(t => t.length > 0) || [];
  let idx = pool[Math.floor(Math.random() * pool.length)];
  if (pool.length > 1 && idx === lastRandomIdx) {
    const alt = pool.filter(i => i !== lastRandomIdx);
    idx = alt[Math.floor(Math.random() * alt.length)];
  }
  lastRandomIdx = idx;
  openDetail(idx);
}

// ========================
// Text Highlight
// ========================
function highlightText(element, term) {
  if (!term || !element) return;
  if (!element.textContent.toLowerCase().includes(term.toLowerCase())) return;
  const lower = term.toLowerCase();
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, null, false);
  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) {
    if (!node.parentElement || node.parentElement.closest('.katex')) continue;
    textNodes.push(node);
  }
  textNodes.forEach(textNode => {
    const text = textNode.textContent;
    const indices = [];
    let pos = 0;
    while ((pos = text.toLowerCase().indexOf(lower, pos)) !== -1) {
      indices.push(pos);
      pos += lower.length;
    }
    if (indices.length === 0) return;
    const frag = document.createDocumentFragment();
    let last = 0;
    indices.forEach(idx => {
      frag.appendChild(document.createTextNode(text.slice(last, idx)));
      const mark = document.createElement('mark');
      mark.className = 'search-mark';
      mark.textContent = text.slice(idx, idx + lower.length);
      frag.appendChild(mark);
      last = idx + lower.length;
    });
    frag.appendChild(document.createTextNode(text.slice(last)));
    textNode.parentNode.replaceChild(frag, textNode);
  });
}

// ========================
// KaTeX Rendering
// ========================
function renderKatex(element) {
  if (!element || !window.katex) return;
  if (element.querySelector && element.querySelector('table')) {
    // 含表格时 prose 与单元格分开渲染；单元格里的 $...$ 公式也要走 KaTeX
    element.querySelectorAll('.stem-prose, .stem-table th, .stem-table td').forEach(renderKatex);
    return;
  }
  let text = element.textContent;
  if (!text) return;

  text = text.replace(/\\n(?![a-zA-Z])/g, '\n');

  let html = '';
  let i = 0;

  while (i < text.length) {
    const c = text[i];

    if (c === '\n') {
      html += '<br>';
      i++;
      continue;
    }

    if (c === '$' && i + 1 < text.length && text[i + 1] === '$') {
      const end = text.indexOf('$$', i + 2);
      if (end !== -1) {
        html += renderMath(text.slice(i + 2, end), true);
        i = end + 2;
        continue;
      }
    }

    if (c === '$') {
      const end = text.indexOf('$', i + 1);
      if (end !== -1) {
        html += renderMath(text.slice(i + 1, end), false);
        i = end + 1;
        continue;
      }
    }

    if (c === '\\' && text[i + 1] === '[') {
      const end = text.indexOf('\\]', i + 2);
      if (end !== -1) {
        html += renderMath(text.slice(i + 2, end), true);
        i = end + 2;
        continue;
      }
    }

    if (c === '\\' && text[i + 1] === '(') {
      const end = text.indexOf('\\)', i + 2);
      if (end !== -1) {
        html += renderMath(text.slice(i + 2, end), false);
        i = end + 2;
        continue;
      }
    }

    if (c === '\\' && i + 1 < text.length && text[i + 1] === '\\') {
      html += '<br>';
      i += 2;
      continue;
    }

    if (c === '\\') {
      const seg = parseLatexSegment(text, i);
      html += renderMath(seg.latex, false);
      i = seg.end;
      continue;
    }

    html += escapeHtml(c);
    i++;
  }

  element.innerHTML = html;
}

const katexCache = new Map();

function renderMath(latex, displayMode) {
  if (!latex || !latex.trim()) return '';
  const key = (displayMode ? 'D:' : 'I:') + latex;
  if (katexCache.has(key)) return katexCache.get(key);
  let html;
  try {
    html = katex.renderToString(latex, {throwOnError: false, displayMode});
    // 若 KaTeX 返回了错误标记，回退为纯文本，避免页面出现大片红色错误提示
    if (html && html.includes('katex-error')) {
      html = `<span class="katex-fallback">${escapeHtml(latex)}</span>`;
    }
  } catch (e) {
    html = `<span class="katex-fallback" title="${escapeHtml(String(e.message))}">${escapeHtml(latex)}</span>`;
  }
  katexCache.set(key, html);
  return html;
}

function parseLatexSegment(s, start) {
  let i = start;

  if (s.startsWith('\\left', i)) {
    i += 5;
    while (i < s.length && /\s/.test(s[i])) i++;
    const leftDelim = s[i] || '';
    i++;

    let depth = 1;
    let j = i;
    while (j < s.length && depth > 0) {
      if (s.startsWith('\\left', j)) { depth++; j += 5; continue; }
      if (s.startsWith('\\right', j)) {
        depth--;
        j += 6;
        if (depth === 0) {
          while (j < s.length && /\s/.test(s[j])) j++;
          if (j < s.length) j++;
          break;
        }
        continue;
      }
      j++;
    }

    const end = collectTrailingArgs(s, j);
    return {latex: s.slice(start, end), end};
  }

  if (s.startsWith('\\begin', i)) {
    i += 6;
    while (i < s.length && s[i] !== '{') i++;
    const envEnd = matchBrace(s, i);
    const env = s.slice(i + 1, envEnd - 1);
    i = envEnd;

    let depth = 1;
    let j = i;
    const beginToken = `\\begin{${env}}`;
    const endToken = `\\end{${env}}`;
    while (j < s.length && depth > 0) {
      if (s.startsWith(beginToken, j)) { depth++; j += beginToken.length; continue; }
      if (s.startsWith(endToken, j)) {
        depth--;
        if (depth === 0) { j += endToken.length; break; }
        j += endToken.length;
        continue;
      }
      j++;
    }

    const end = collectTrailingArgs(s, j);
    return {latex: s.slice(start, end), end};
  }

  i++;
  if (i < s.length && /[a-zA-Z]/.test(s[i])) {
    while (i < s.length && /[a-zA-Z]/.test(s[i])) i++;
  } else if (i < s.length) {
    i++;
  }

  i = collectTrailingArgs(s, i);
  return {latex: s.slice(start, i), end: i};
}

function collectTrailingArgs(s, i) {
  while (i < s.length) {
    if (s[i] === '^' || s[i] === '_') {
      i++;
      if (s[i] === '{') i = matchBrace(s, i);
      else i++;
    } else if (s[i] === '{' || s[i] === '[') {
      i = matchBrace(s, i);
    } else {
      break;
    }
  }
  return i;
}

function matchBrace(s, i) {
  const open = s[i];
  const close = open === '{' ? '}' : ']';
  let depth = 1;
  let j = i + 1;
  while (j < s.length && depth > 0) {
    if (s[j] === open) depth++;
    else if (s[j] === close) depth--;
    j++;
  }
  return j;
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ========================
// Events
// ========================
function setupEvents() {
  const searchInput = document.getElementById('searchInput');
  searchInput.addEventListener('input', debounce(() => {
    resetAndFilter();
  }, 200));
  // 搜索历史：仅 Enter / 失焦 且长度≥2 时写入
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const term = searchInput.value.trim();
      if (term.length >= 2) pushSearchHistory(term);
      const dd = document.getElementById('searchHistoryDropdown');
      if (dd) dd.hidden = true;
      searchInput.blur();
    }
  });
  searchInput.addEventListener('blur', () => {
    const term = searchInput.value.trim();
    if (term.length >= 2) pushSearchHistory(term);
  });
  searchInput.addEventListener('focus', renderSearchHistoryDropdown);
  document.getElementById('typeFilter').addEventListener('change', resetAndFilter);
  document.getElementById('featureFilter').addEventListener('change', resetAndFilter);
  const sortSel = document.getElementById('sortSelect');
  if (sortSel) sortSel.addEventListener('change', () => { currentPage = 1; applyFilters(); });

  document.getElementById('btnPractice').addEventListener('click', () => startPractice());
  document.getElementById('btnRandom').addEventListener('click', randomQuestion);
  document.getElementById('btnExport').addEventListener('click', exportProgress);
  const btnResume = document.getElementById('btnResumePos');
  const btnDismiss = document.getElementById('btnDismissResume');
  if (btnResume) btnResume.addEventListener('click', resumeLastPosition);
  if (btnDismiss) btnDismiss.addEventListener('click', clearCursor);
  setupPlatformSyncEvents();
  document.getElementById('btnImport').addEventListener('click', () => document.getElementById('importFile').click());
  document.getElementById('btnExportNotes').addEventListener('click', exportNotesAsMarkdown);
  document.getElementById('btnBackupNow').addEventListener('click', () => triggerBackup(false));
  document.getElementById('importFile').addEventListener('change', (e) => {
    importProgress(e.target.files[0]);
    e.target.value = '';
  });
  document.getElementById('helpToggle').addEventListener('click', openHelp);
  document.getElementById('dashboardToggle').addEventListener('click', openDashboard);
  document.getElementById('wrongBookBtn').addEventListener('click', openWrongBook);
  document.getElementById('paperBtn').addEventListener('click', openPaper);
  const viewBtn = document.getElementById('btnViewToggle');
  if (viewBtn) viewBtn.addEventListener('click', toggleViewMode);
  const wbGroup = document.getElementById('wrongBookGroupBy');
  if (wbGroup) wbGroup.addEventListener('change', renderWrongBook);
  // 试卷配置 change
  ['paperCourse','paperChapter','paperType','paperCount','paperShuffle'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('change', () => { if (id === 'paperCourse') updatePaperChapters(); generatePaper(); });
  });
  const moreBtn = document.getElementById('btnMoreMobile');
  const moreMenu = document.getElementById('mobileMoreMenu');
  if (moreBtn && moreMenu) {
    moreBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      moreMenu.hidden = !moreMenu.hidden;
    });
    moreMenu.addEventListener('click', (e) => {
      const item = e.target.closest('[data-action]');
      if (!item) return;
      moreMenu.hidden = true;
      const act = item.dataset.action;
      if (act === 'export') exportProgress();
      else if (act === 'import') document.getElementById('importFile').click();
      else if (act === 'notes') exportNotesAsMarkdown();
      else if (act === 'backup') triggerBackup(false);
      else if (act === 'view') toggleViewMode();
      else if (act === 'random') randomQuestion();
    });
    document.addEventListener('click', () => { moreMenu.hidden = true; });
  }

  const practiceArrow = document.getElementById('btnPracticeArrow');
  const practiceMenu = document.getElementById('practiceMenu');
  if (practiceArrow && practiceMenu) {
    practiceArrow.addEventListener('click', (e) => {
      e.stopPropagation();
      practiceMenu.hidden = !practiceMenu.hidden;
    });
    practiceMenu.addEventListener('click', (e) => {
      const item = e.target.closest('.split-menu-item');
      if (!item) return;
      practiceMenu.hidden = true;
      const mode = item.dataset.mode;
      if (mode === 'current' || !mode) startPractice();
      else startPractice(mode);
    });
    document.addEventListener('click', () => { practiceMenu.hidden = true; });
  }
  document.getElementById('toggleSidebar').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
  });
  const dueBtn = document.getElementById('btnDueReview');
  if (dueBtn) dueBtn.addEventListener('click', () => {
    if (window.innerWidth <= 768) document.getElementById('sidebar').classList.remove('open');
    startPractice('review');
  });
  document.getElementById('sidebarOverlay').addEventListener('click', () => {
    document.getElementById('sidebar').classList.remove('open');
  });

  const mobileSel = document.getElementById('mobileCourseSelect');
  if (mobileSel) mobileSel.addEventListener('change', (e) => switchCourse(e.target.value));

  function handleCardActivation(e) {
    if (e.type === 'keydown' && e.key !== 'Enter') return;
    const card = e.target.closest('.question-card') || e.target.closest('.question-row');
    if (card) openDetail(Number(card.dataset.index));
  }
  document.getElementById('questionGrid').addEventListener('click', handleCardActivation);
  document.getElementById('questionGrid').addEventListener('keydown', handleCardActivation);

  ['detailModal', 'practiceModal', 'helpModal', 'dashboardModal', 'wrongBookModal', 'paperModal'].forEach(id => {
    document.getElementById(id).addEventListener('click', (e) => {
      if (e.target === e.currentTarget) closeModalById(id);
    });
  });

  document.addEventListener('keydown', (e) => {
    const inEditable = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable);
    if (e.key === 'Escape') {
      if (inEditable && e.target.id === 'searchInput') {
        e.target.blur();
        const dd = document.getElementById('searchHistoryDropdown');
        if (dd) dd.hidden = true;
        return;
      }
      closeModalById('detailModal');
      closeModalById('practiceModal');
      closeModalById('helpModal');
      closeModalById('dashboardModal');
      closeModalById('wrongBookModal');
      closeModalById('paperModal');
      const dd = document.getElementById('searchHistoryDropdown');
      if (dd) dd.hidden = true;
    }
    if (inEditable) return;
    if (e.key === '?' && !document.querySelector('.modal-overlay.active')) {
      e.preventDefault();
      openHelp();
    }
    if (e.key === '/' && !document.querySelector('.modal-overlay.active')) {
      e.preventDefault();
      const inp = document.getElementById('searchInput');
      inp.focus();
      inp.select();
      renderSearchHistoryDropdown();
    }
    const detailActive = document.getElementById('detailModal').classList.contains('active');
    if (detailActive) {
      if (e.key === 'ArrowLeft') { e.preventDefault(); prevQuestion(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); nextQuestion(); }
      if (e.key === '1') { e.preventDefault(); setDetailMastery('mastered'); }
      if (e.key === '2') { e.preventDefault(); setDetailMastery('familiar'); }
      if (e.key === '3') { e.preventDefault(); setDetailMastery('unknown'); }
      if (e.key === 'f' || e.key === 'F') { e.preventDefault(); toggleDetailFavorite(); }
      if (e.key === 'c' || e.key === 'C') {
        const q = getCurrentDetailQuestion();
        if (q) copyQuestionToClipboard(q);
      }
      const optKey = e.key.toUpperCase();
      if (['A', 'B', 'C', 'D'].includes(optKey)) {
        const container = document.getElementById('modalContent');
        const opt = container && container.querySelector(`.option-item[data-key="${optKey}"]`);
        if (opt && !container._submitted) { e.preventDefault(); opt.click(); }
      }
    }
    const practiceActive = document.getElementById('practiceModal').classList.contains('active');
    if (practiceActive && !practiceFinished) {
      if (e.key === 'ArrowLeft') { e.preventDefault(); prevPractice(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); nextPractice(); }
      const container = document.getElementById('practiceContent');
      const optKey = e.key.toUpperCase();
      if (['A', 'B', 'C', 'D'].includes(optKey)) {
        const opt = container && container.querySelector(`.option-item[data-key="${optKey}"]`);
        if (opt && !container._submitted) { e.preventDefault(); opt.click(); }
      }
      if (e.key === ' ' || e.key === 'Enter') {
        const reveal = container && container.querySelector('[data-role="revealBtn"]');
        if (reveal && !reveal.disabled) { e.preventDefault(); reveal.click(); }
      }
      if (e.key === '1' || e.key === '2' || e.key === '3') {
        const map = { '1': 'mastered', '2': 'familiar', '3': 'unknown' };
        const box = container && container.querySelector('[data-role="practiceMastery"]');
        if (box && !box.hidden && container._q) {
          e.preventDefault();
          setMastery(container._q, map[e.key]);
          box.hidden = true;
        }
      }
    }
  });
  // 点击外部关闭搜索历史下拉
  document.addEventListener('click', (e) => {
    const dd = document.getElementById('searchHistoryDropdown');
    const box = document.querySelector('.search-box');
    if (dd && box && !box.contains(e.target)) dd.hidden = true;
  });
}

// Initialize
// ========================
// 同步掌握度 → 考研平台（StudyRecord / 错题本）
// 须从 http://127.0.0.1:8000/banks/408/ 打开（同源 API）
// uid: 408:{cs408-*}::{chapter.name}::{qid}
// 标记「会了/不熟/不会」后会自动同步；也可用顶栏「同步平台」批量补同步
// ========================
const COURSE_TO_SUBJECT = {
  '数据结构': 'cs408-ds',
  '计算机组成原理': 'cs408-coa',
  '操作系统': 'cs408-os',
  '计算机网络': 'cs408-net',
};

function isPlatformHost() {
  try {
    const host = String(location.host || '');
    const path = String(location.pathname || '');
    // 平台挂载：:8000/banks/408/… ；兼容 localhost / 127.0.0.1
    if (/:8000$/i.test(host)) return true;
    if (path.indexOf('/banks/408') === 0) return true;
    return false;
  } catch (e) {
    return false;
  }
}

function platformBankCode(q) {
  const course = (q && q.course) || getCurrentCourse() || '';
  return COURSE_TO_SUBJECT[course] || 'cs408-ds';
}

function platformSourceUid(q) {
  if (!q) return '';
  const code = platformBankCode(q);
  const ch = q.chapter || '';
  const id = q.id || '';
  if (!ch || !id) return '';
  return '408:' + code + '::' + ch + '::' + id;
}

function masteryToPlatformMark(mastery) {
  if (mastery === 'mastered') return 'mastered';
  if (mastery === 'familiar') return 'familiar';
  if (mastery === 'unknown') return 'unknown';
  return null;
}

/** 平台 mark → 408 mastery（兼容 math 词表） */
function platformMarkToMastery(mark) {
  const m = String(mark || '');
  if (m === 'mastered') return 'mastered';
  if (m === 'familiar' || m === 'fuzzy') return 'familiar';
  if (m === 'unknown' || m === 'forgot') return 'unknown';
  return '';
}

/**
 * 平台 → 本地：按 source_uid 合并熟练度。
 * mode: fill | overwrite | prefer_weaker（默认）
 */
async function pullMasteryFromPlatform(opts) {
  opts = opts || {};
  if (!isPlatformHost()) {
    if (!opts.silent) platformSyncToast('请从平台打开本题库后再拉取', 4000);
    return { applied: 0, skipped: 0 };
  }
  if (!window.ViewerPlatformSync || !ViewerPlatformSync.pullMasteryFromPlatform) {
    if (!opts.silent) platformSyncToast('同步脚本未加载', 3000);
    return { applied: 0, skipped: 0 };
  }
  if (!opts.silent) platformSyncToast('正在从平台拉取熟练度…', 2000);

  // 一次拉全 408（四科 source_uid 均以 408: 开头）
  const out = await ViewerPlatformSync.pullMasteryFromPlatform('408', { scheme: '408' });
  if (!out.ok) {
    if (!opts.silent) platformSyncToast('拉取失败：' + (out.error || '未知错误'), 5000);
    return { applied: 0, skipped: 0 };
  }
  const items = (out.data && out.data.items) || [];
  if (!items.length) {
    if (!opts.silent) platformSyncToast('平台暂无本库答题记录', 3000);
    return { applied: 0, skipped: 0 };
  }

  // 建 uid → question 索引
  const byUid = new Map();
  (allQuestions || []).forEach(q => {
    const uid = platformSourceUid(q);
    if (uid) byUid.set(uid, q);
  });

  const mode = opts.mode || 'prefer_weaker';
  let applied = 0;
  let skipped = 0;
  items.forEach(it => {
    const q = byUid.get(it.uid);
    if (!q) {
      skipped++;
      return;
    }
    const remote = platformMarkToMastery(it.mark);
    if (!remote) {
      skipped++;
      return;
    }
    const local = getMastery(q) || '';
    const localEmpty = !local;
    let take = false;
    if (mode === 'overwrite') take = local !== remote;
    else if (mode === 'fill') take = localEmpty;
    else {
      // prefer_weaker
      if (localEmpty) take = true;
      else if (ViewerPlatformSync.markRank(remote) > ViewerPlatformSync.markRank(local)) take = true;
    }
    if (!take) {
      skipped++;
      return;
    }
    // 直接写 statusMap，避免 setMastery 触发回推形成循环
    const key = questionKey(q);
    const entry = getStatusEntry(key);
    entry.mastery = remote;
    writeStatusEntry(key, entry);
    applied++;
  });
  if (applied > 0) {
    saveStatus();
    try {
      renderStats();
      renderMarkDashboard();
      refreshChapterMastery();
      const searchEl = document.getElementById('searchInput');
      const search = searchEl ? searchEl.value.trim().toLowerCase() : '';
      renderGrid(search);
    } catch (e) {}
  }
  if (!opts.silent) {
    platformSyncToast(
      '已从平台拉取：更新 ' + applied + (skipped ? '，跳过 ' + skipped : '') + ' · 会了/不熟/不会',
      4500
    );
  }
  return { applied, skipped };
}

function platformSyncToast(msg, ms) {
  // 同步结果展示久一点，避免用户看不到
  let el = document.getElementById('flashToast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'flashToast';
    el.className = 'flash-toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(platformSyncToast._t);
  platformSyncToast._t = setTimeout(() => el.classList.remove('show'), ms || 3500);
}

async function ensurePlatformToken() {
  if (window.ViewerPlatformSync && ViewerPlatformSync.ensureAuth) {
    const auth = await ViewerPlatformSync.ensureAuth();
    if (auth.ok) return auth.token || true; // true = cookie session
    return null;
  }
  // viewer-common 未加载：只认旧 localStorage token，不再 POST auto-login（公网必 401/404）
  try { return localStorage.getItem('token'); } catch (e) {}
  return null;
}

function gatherPlatformSyncItems(scope) {
  let pool = allQuestions;
  if (scope === 'current') pool = filteredQuestions;
  const items = [];
  pool.forEach(q => {
    if (q.type && q.type !== '选择题') return;
    const mark = masteryToPlatformMark(getMastery(q));
    if (!mark) return;
    if (scope === 'weak' && mark === 'mastered') return;
    const uid = platformSourceUid(q);
    if (!uid) return;
    items.push({
      uid: uid,
      mark: mark,
      title: q.content || '',
      chapter: q.chapter || '',
      bank: platformBankCode(q),
    });
  });
  return items;
}

async function postSyncToPlatform(items, opts) {
  opts = opts || {};
  if (!isPlatformHost()) {
    platformSyncToast('请从平台打开本题库：http://127.0.0.1:8000/banks/408/', 5000);
    return { ok: 0, fail: items.length || 0 };
  }
  if (!items || !items.length) {
    if (!opts.silentEmpty) platformSyncToast('没有可同步的标记（会了/不熟/不会）');
    return { ok: 0, fail: 0 };
  }
  const token = await ensurePlatformToken();
  if (!token) {
    platformSyncToast('未登录：请先打开平台首页 http://127.0.0.1:8000/', 5000);
    return { ok: 0, fail: items.length };
  }
  if (!opts.silent) platformSyncToast('正在同步 ' + items.length + ' 题到平台…', 2000);

  const byBank = {};
  items.forEach(it => {
    const code = it.bank || (it.uid.split('::')[0] || '').replace(/^408:/, '') || 'cs408-ds';
    if (!byBank[code]) byBank[code] = [];
    byBank[code].push({ uid: it.uid, mark: it.mark, title: it.title, chapter: it.chapter });
  });

  let ok = 0, fail = 0;
  const failSamples = [];
  const bearer = typeof token === 'string' ? token : null;
  for (const [bank, list] of Object.entries(byBank)) {
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (bearer) headers.Authorization = 'Bearer ' + bearer;
      const r = await fetch('/api/study-records/sync-from-bank', {
        method: 'POST',
        credentials: 'include',
        headers: headers,
        body: JSON.stringify({ bank: bank, items: list }),
      });
      let data = {};
      try { data = await r.json(); } catch (e) {}
      if (!r.ok) {
        fail += list.length;
        const detail = data.detail;
        failSamples.push(typeof detail === 'string' ? detail : ('HTTP ' + r.status));
        continue;
      }
      ok += data.ok_count || 0;
      fail += data.failed_count || 0;
      (data.failed || []).slice(0, 3).forEach(f => {
        failSamples.push((f.uid || '').split('::').slice(-1)[0] + ':' + (f.reason || '?'));
      });
    } catch (e) {
      fail += list.length;
      failSamples.push(String(e.message || e));
    }
  }
  if (!(opts.quietSuccess && ok && !fail)) {
    let msg = '已写入平台：成功 ' + ok + (fail ? '，失败 ' + fail : '');
    if (failSamples.length) msg += '（' + failSamples.slice(0, 2).join('；') + '）';
    if (ok && !fail) msg += ' · 回首页刷新可看进度';
    platformSyncToast(msg, fail ? 6000 : 4000);
  }
  return { ok: ok, fail: fail };
}

async function syncMasteryToPlatform(scope) {
  const items = gatherPlatformSyncItems(scope || 'all');
  return postSyncToPlatform(items, { silent: false });
}

/** 单题自动同步（标记后触发） */
const _autoSyncQueue = [];
let _autoSyncTimer = null;
let _autoSyncInFlight = false;
let _autoSyncRetryCount = 0;
let _platformSyncBarHideTimer = null;

const AUTO_SYNC_RETRY_DELAYS = [1500, 5000, 15000, 30000];

function upsertAutoSyncItem(item) {
  const idx = _autoSyncQueue.findIndex(x => x.uid === item.uid);
  if (idx >= 0) _autoSyncQueue[idx] = item;
  else _autoSyncQueue.push(item);
}

function scheduleAutoSyncFlush(delay) {
  clearTimeout(_autoSyncTimer);
  _autoSyncTimer = setTimeout(() => {
    _autoSyncTimer = null;
    flushAutoSyncQueue();
  }, delay == null ? 300 : delay);
}

async function flushAutoSyncQueue() {
  if (_autoSyncInFlight || !_autoSyncQueue.length) return;
  _autoSyncInFlight = true;
  const batch = _autoSyncQueue.splice(0, _autoSyncQueue.length);
  try {
    const result = await postSyncToPlatform(batch, { silent: true, quietSuccess: true });
    if (result && result.ok > 0 && result.fail === 0) {
      _autoSyncRetryCount = 0;
      try { localStorage.setItem('wd408_last_sync_sig', masterySignature()); } catch (e) {}
    } else {
      // 请求失败时重新入队；相同 uid 仍以用户最新一次标记为准。
      batch.forEach(item => {
        if (!_autoSyncQueue.some(x => x.uid === item.uid)) upsertAutoSyncItem(item);
      });
      const idx = Math.min(_autoSyncRetryCount, AUTO_SYNC_RETRY_DELAYS.length - 1);
      _autoSyncRetryCount++;
      scheduleAutoSyncFlush(AUTO_SYNC_RETRY_DELAYS[idx]);
    }
  } catch (e) {
    batch.forEach(item => {
      if (!_autoSyncQueue.some(x => x.uid === item.uid)) upsertAutoSyncItem(item);
    });
    const idx = Math.min(_autoSyncRetryCount, AUTO_SYNC_RETRY_DELAYS.length - 1);
    _autoSyncRetryCount++;
    scheduleAutoSyncFlush(AUTO_SYNC_RETRY_DELAYS[idx]);
  } finally {
    _autoSyncInFlight = false;
    if (_autoSyncQueue.length && !_autoSyncTimer) scheduleAutoSyncFlush();
    hidePlatformSyncBar();
  }
}

function queueAutoSyncToPlatform(q) {
  if (!isPlatformHost() || !q) return;
  if (q.type && q.type !== '选择题') return;
  const mark = masteryToPlatformMark(getMastery(q));
  if (!mark) return;
  const uid = platformSourceUid(q);
  if (!uid) return;
  const item = {
    uid: uid,
    mark: mark,
    title: q.content || '',
    chapter: q.chapter || '',
    bank: platformBankCode(q),
  };
  // 同 uid 覆盖为最新 mark；失败时由 flushAutoSyncQueue 自动重试。
  upsertAutoSyncItem(item);
  _autoSyncRetryCount = 0;
  scheduleAutoSyncFlush(250);
}

function setupPlatformSyncEvents() {
  const btn = document.getElementById('btnPlatformSync');
  const menu = document.getElementById('platformSyncMenu');
  const hint = document.getElementById('platformSyncHint');
  if (hint) {
    hint.style.display = '';
    hint.textContent = isPlatformHost()
      ? '已自动同步 · 手动按钮仅作备用'
      : '请从学习平台打开本题库才能同步';
  }
  if (!btn || !menu) return;
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!isPlatformHost()) {
      platformSyncToast('请从 http://127.0.0.1:8000/banks/408/ 打开本题库', 5000);
      return;
    }
    const open = menu.hidden;
    menu.hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  menu.querySelectorAll('[data-sync-scope]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      syncMasteryToPlatform(el.getAttribute('data-sync-scope'));
    });
  });
  menu.querySelectorAll('[data-sync-pull]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      pullMasteryFromPlatform({ silent: false, mode: 'prefer_weaker' });
    });
  });
  document.addEventListener('click', () => {
    if (!menu.hidden) {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    }
  });
}

/** 本地掌握标记签名：变化则需要再推平台 */
function masterySignature() {
  const parts = [];
  try {
    Object.keys(statusMap || {}).forEach(k => {
      const e = normalizeStatusEntry(statusMap[k]);
      if (e.mastery) parts.push(k + '=' + e.mastery);
    });
  } catch (e) {}
  parts.sort();
  return parts.join('|');
}

function localMarkedChoiceCount() {
  return gatherPlatformSyncItems('all').length;
}

/** 自动同步不展示 UI；底部条默认隐藏 */
function hidePlatformSyncBar() {
  const bar = document.getElementById('platformSyncBar');
  if (!bar) return;
  clearTimeout(_platformSyncBarHideTimer);
  bar.hidden = true;
}

function updatePlatformSyncBar(/* state */) {
  // 后台自动同步：不显示底部提示条
  hidePlatformSyncBar();
}

/**
 * 打开题库 / 标记变化：
 * 1) 先从平台拉取熟练度（反向，补本地）
 * 2) 再把本地掌握度推到平台（静默）
 */
async function maybeAutoPushMasteryToPlatform(force) {
  hidePlatformSyncBar();
  if (!isPlatformHost()) return;

  // 每会话自动拉一次平台 → 本地
  let pulled = false;
  try {
    pulled = sessionStorage.getItem('wd408_pull_session') === '1';
  } catch (e) {}
  if (!pulled || force) {
    try {
      // 自动拉取只补本地空白，避免平台旧状态覆盖刚在本地修改但尚未上传的标记。
      await pullMasteryFromPlatform({ silent: true, mode: 'fill' });
      sessionStorage.setItem('wd408_pull_session', '1');
    } catch (e) {}
  }

  const items = gatherPlatformSyncItems('all');
  if (!items.length) return;

  // 每个浏览器会话强制全量推一次：平台重导题库后 question_id 会变
  let sessionForced = false;
  try {
    sessionForced = sessionStorage.getItem('wd408_force_sync_session') === '1';
  } catch (e) {}
  if (!force && !sessionForced) {
    force = true;
    try { sessionStorage.setItem('wd408_force_sync_session', '1'); } catch (e) {}
  }

  const sig = masterySignature();
  let lastSig = '';
  try { lastSig = localStorage.getItem('wd408_last_sync_sig') || ''; } catch (e) {}
  if (!force && sig && sig === lastSig) return;

  const result = await postSyncToPlatform(items, { silent: true, quietSuccess: true });
  if (result && result.ok > 0 && result.fail === 0) {
    try { localStorage.setItem('wd408_last_sync_sig', sig); } catch (e) {}
  } else {
    // 部分/全部失败：清签名，下次打开或 3s 重试时再推
    try { localStorage.setItem('wd408_last_sync_sig', ''); } catch (e) {}
  }
  hidePlatformSyncBar();
}

let _automaticPlatformSyncReady = false;
let _automaticPlatformSyncRunning = false;
let _automaticPlatformSyncInterval = null;

/**
 * 自动同步总控：
 * - 打开题库立即双向同步；
 * - 每 30 秒检查本地标记变化并补推；
 * - 切回页面、恢复网络、其他标签页修改本地进度时立即补同步。
 */
function setupAutomaticPlatformSync() {
  if (_automaticPlatformSyncReady || !isPlatformHost()) return;
  _automaticPlatformSyncReady = true;

  const run = async (force) => {
    if (_automaticPlatformSyncRunning) return;
    _automaticPlatformSyncRunning = true;
    try {
      await maybeAutoPushMasteryToPlatform(!!force);
      await submitQuestionIssueQueue({silent: true});
      if (_autoSyncQueue.length) scheduleAutoSyncFlush(0);
    } finally {
      _automaticPlatformSyncRunning = false;
    }
  };

  setTimeout(() => run(true), 350);
  _automaticPlatformSyncInterval = setInterval(() => run(false), 30000);
  window.addEventListener('online', () => run(true));
  window.addEventListener('focus', () => run(true));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) run(true);
  });
  window.addEventListener('storage', (e) => {
    if (e.key === STATUS_KEY) run(false);
  });
}

// 覆盖 setup 里对同步条按钮的绑定
function setupPlatformSyncBarBtn() {
  const btn = document.getElementById('platformSyncBarBtn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await maybeAutoPushMasteryToPlatform(true);
    } finally {
      btn.disabled = false;
    }
  });
}

const _origSetupPlatformSyncEvents = setupPlatformSyncEvents;
setupPlatformSyncEvents = function () {
  _origSetupPlatformSyncEvents();
  setupPlatformSyncBarBtn();
};

init();

// PWA：注册 Service Worker（换 CACHE 版本后主动 update，避免旧 CSS 一直 stale）
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js?v=259').then((reg) => {
      reg.update().catch(() => {});
      console.log('[SW] registered, scope:', reg.scope);
    }).catch((err) => {
      console.warn('[SW] registration failed:', err);
    });
  });
}

// ========================
// 备份提醒：超过 30 天未备份时显示非强制提示，用户点击后才下载
// ========================
const BACKUP_KEY = 'mathbank_last_backup_at';
const BACKUP_REMIND_KEY = 'mathbank_backup_reminded_at';
const BACKUP_INTERVAL = 30 * 86400000;  // 30 天
function maybeShowBackupReminder() {
  try {
    const now = Date.now();
    const lastBackup = parseInt(localStorage.getItem(BACKUP_KEY) || '0', 10);
    const lastRemind = parseInt(localStorage.getItem(BACKUP_REMIND_KEY) || '0', 10);
    // 全新用户首次使用不提醒（还没有进度可备份），只播种提醒时间
    if (!lastBackup && !lastRemind) {
      safeSetItem(BACKUP_REMIND_KEY, String(now));
      return;
    }
    if (now - Math.max(lastBackup, lastRemind) < BACKUP_INTERVAL) return;
    // 先记录提醒时间，保证最多每 30 天提示一次（无论用户点不点）
    safeSetItem(BACKUP_REMIND_KEY, String(now));
    showBackupReminder();
  } catch(e) {}
}
function showBackupReminder() {
  if (document.getElementById('backupReminder')) return;
  const el = document.createElement('div');
  el.id = 'backupReminder';
  el.className = 'backup-reminder';
  el.innerHTML = '<span>进度已 30 天未备份，建议导出一份</span>' +
    '<button type="button" id="backupReminderGo">立即备份</button>' +
    '<button type="button" id="backupReminderClose" aria-label="关闭">×</button>';
  document.body.appendChild(el);
  el.querySelector('#backupReminderGo').addEventListener('click', () => {
    triggerBackup(false);
    el.remove();
  });
  el.querySelector('#backupReminderClose').addEventListener('click', () => el.remove());
  requestAnimationFrame(() => el.classList.add('show'));
}
function triggerBackup(silent) {
  try {
    const data = buildFullExportPayload();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `mathbank-backup-${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    safeSetItem(BACKUP_KEY, String(Date.now()));
    if (!silent) flashToast('已下载完整备份');
    return true;
  } catch(e) {
    if (!silent) flashToast('备份失败：' + e.message);
    return false;
  }
}

// 启动后异步检查是否该提醒（只显示提示，绝不自动下载）
setTimeout(maybeShowBackupReminder, 3000);
