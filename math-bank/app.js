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

const STATUS_KEY = 'mathbank_status_v1';
let statusMap = {};

function questionKey(q) { return q.chapter + '::' + q.id; }
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

function openModal(id) {
  document.getElementById(id).classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModalById(id) {
  document.getElementById(id).classList.remove('active');
  document.body.style.overflow = '';
}

function getAvailableCourses() {
  if (bank && bank.courses) return bank.courses;
  if (window.__COURSE_MANIFEST__) {
    return window.__COURSE_MANIFEST__.map(c => ({name: c.name, short: c.short, question_count: c.question_count}));
  }
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
// Status (favorite / correct / wrong)
// ========================
function loadStatus() {
  try {
    const raw = localStorage.getItem(STATUS_KEY);
    statusMap = raw ? JSON.parse(raw) : {};
  } catch (e) {
    statusMap = {};
  }
}

function saveStatus() {
  try {
    localStorage.setItem(STATUS_KEY, JSON.stringify(statusMap));
  } catch (e) {}
}

function getStatus(q) {
  return statusMap[questionKey(q)] || '';
}

function setStatus(q, status) {
  const key = questionKey(q);
  if (!status) delete statusMap[key];
  else statusMap[key] = status;
  saveStatus();
}

function toggleFavorite(q) {
  const key = questionKey(q);
  if (statusMap[key] === 'favorite') delete statusMap[key];
  else statusMap[key] = 'favorite';
  saveStatus();
  renderStats();
  const search = document.getElementById('searchInput').value.trim().toLowerCase();
  renderGrid(search);
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
  if (course) {
    document.getElementById('resultText').textContent = '正在加载课程数据…';
    await loadBankData(course);
  }

  currentChapters = getCurrentChapters();
  buildAllQuestions();

  renderChapters();
  renderStats();
  applyFilters();
  setupEvents();
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

  document.querySelectorAll('.course-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.course === course);
  });
  const sel = document.getElementById('mobileCourseSelect');
  if (sel) sel.value = course;
  currentPage = 1;
  renderChapters();
  renderStats();
  applyFilters();
}

// ========================
// Sidebar - 三级折叠树
// ========================
function buildChapterTree() {
  const l1Map = new Map();
  for (const ch of currentChapters) {
    const l1 = ch.l1_name || '?';
    const l2 = ch.l2_name || '';
    const sec = ch.section_type || '';
    if (!l1Map.has(l1)) l1Map.set(l1, { name: l1, total: 0, l2Map: new Map() });
    const l1Node = l1Map.get(l1);
    l1Node.total += ch.question_count;
    const l2Key = l2;
    if (!l1Node.l2Map.has(l2Key)) l1Node.l2Map.set(l2Key, { name: l2, total: 0, sections: [] });
    const l2Node = l1Node.l2Map.get(l2Key);
    l2Node.total += ch.question_count;
    l2Node.sections.push({
      name: ch.name,
      section_type: sec,
      question_count: ch.question_count,
      key: l1 + '|' + l2 + '|' + sec
    });
  }
  return l1Map;
}

function makeToggle(text, count, extraClass, dataset, unsafe) {
  const btn = document.createElement('button');
  btn.className = 'tree-toggle ' + (extraClass || '');
  if (dataset) btn.dataset.key = dataset;
  const label = unsafe ? text : escapeHtml(text);
  btn.innerHTML = '<span class="arrow"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg></span><span style="flex:1">' + label + '</span><span class="count">' + count + '</span>';
  return btn;
}

function renderChapters() {
  const container = document.getElementById('chapterList');
  container.innerHTML = '';

  const allWrap = document.createElement('div');
  const allItem = makeToggle('全部章节', allQuestions.length, 'tree-l1 all-item' + (selectedChapter ? '' : ' active'), '');
  allItem.onclick = (e) => {
    e.stopPropagation();
    selectChapter('', allItem);
  };
  allWrap.appendChild(allItem);
  container.appendChild(allWrap);

  const tree = buildChapterTree();

  for (const [l1Name, l1Node] of tree.entries()) {
    const l1Wrap = document.createElement('div');
    const l1Btn = makeToggle(l1Name, l1Node.total, 'tree-l1', '');
    const l1Children = document.createElement('div');
    l1Children.className = 'tree-children';

    l1Btn.onclick = (e) => {
      e.stopPropagation();
      const exp = l1Btn.classList.toggle('expanded');
      l1Children.classList.toggle('show', exp);
    };

    for (const [l2Name, l2Node] of l1Node.l2Map.entries()) {
      const l2Wrap = document.createElement('div');
      l2Wrap.className = 'tree-l2-wrap';
      const l2Btn = makeToggle(l2Name, l2Node.total, 'tree-l2', '');
      const l2Children = document.createElement('div');
      l2Children.className = 'tree-children';

      l2Btn.onclick = (e) => {
        e.stopPropagation();
        const exp = l2Btn.classList.toggle('expanded');
        l2Children.classList.toggle('show', exp);
      };

      for (const sec of l2Node.sections) {
        const icon = sec.section_type === '选择题' ? '<svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10"/></svg>' : '<svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><polygon points="12,2 22,22 2,22"/></svg>';
        const cls = 'tree-l3 ' + (sec.section_type === '选择题' ? 'choice' : 'nonchoice');
        const l3Btn = makeToggle(sec.section_type, sec.question_count, cls, sec.key);
        l3Btn.querySelector('.arrow').innerHTML = icon;
        l3Btn.onclick = (e) => {
          e.stopPropagation();
          l1Btn.classList.add('expanded');
          l1Children.classList.add('show');
          l2Btn.classList.add('expanded');
          l2Children.classList.add('show');
          selectChapter(sec.key, l3Btn);
        };
        l2Children.appendChild(l3Btn);
      }

      l2Wrap.appendChild(l2Btn);
      l2Wrap.appendChild(l2Children);
      l1Children.appendChild(l2Wrap);
    }

    l1Wrap.appendChild(l1Btn);
    l1Wrap.appendChild(l1Children);
    container.appendChild(l1Wrap);
  }

  if (selectedChapter) {
    const buttons = container.querySelectorAll('.tree-l3');
    for (const btn of buttons) {
      if (btn.dataset.key === selectedChapter) {
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
  }
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
  let favCount = 0, wrongCount = 0, doneCount = 0;
  allQuestions.forEach(q => {
    types[q.type] = (types[q.type] || 0) + 1;
    if (q.sub_questions) counts.sub++;
    if (q.has_image) counts.image++;
    const st = getStatus(q);
    if (st === 'favorite') favCount++;
    else if (st === 'wrong') wrongCount++;
    if (st === 'correct' || st === 'wrong') doneCount++;
  });

  const stats = [
    {label: '总题数', value: allQuestions.length, action: 'all'},
    {label: '选择', value: types['选择题'] || 0, action: '选择题'},
    {label: '解答', value: types['解答题'] || 0, action: '解答题'},
    {label: '子问', value: counts.sub, action: 'sub'},
    {label: '图片', value: counts.image, action: 'image'},
    {label: '收藏', value: favCount, action: 'favorite', kind: 'status'},
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
    if (opts.chapter && q.chapterKey !== opts.chapter) return false;
    if (opts.type && q.type !== opts.type) return false;
    if (opts.feature === 'sub' && !q.sub_questions) return false;
    if (opts.feature === 'image' && !q.has_image) return false;
    if (opts.status) {
      const st = getStatus(q);
      if (opts.status === 'done' && st !== 'correct' && st !== 'wrong') return false;
      if (opts.status !== 'done' && st !== opts.status) return false;
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

  const chapterLabel = selectedChapter ? selectedChapter.replace(/\|/g, ' · ') : '';
  document.getElementById('resultText').innerHTML =
    `共 <strong>${filteredQuestions.length}</strong> 道题目${chapterLabel ? ' · <span style="color:var(--text-secondary)">' + escapeHtml(chapterLabel) + '</span>' : ''}`;

  currentPage = Math.min(currentPage, Math.max(1, getTotalPages()));
  renderGrid(search);
  renderPagination();
  renderStats();
  syncUrl();
}

// ========================
// Grid Rendering (List View)
// ========================
function statusIconsHtml(q) {
  const st = getStatus(q);
  if (!st) return '';
  const star = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
  const check = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
  const cross = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
  if (st === 'favorite') return `<span class="status-icon fav fav-btn" data-fav="1" title="取消收藏">${star}</span>`;
  if (st === 'correct') return `<span class="status-icon ok" title="已做对">${check}</span>`;
  if (st === 'wrong') return `<span class="status-icon bad" title="已做错">${cross}</span>`;
  return '';
}

function renderGrid(search) {
  const grid = document.getElementById('questionGrid');
  const start = (currentPage - 1) * pageSize;
  const pageQs = filteredQuestions.slice(start, start + pageSize);

  if (pageQs.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        <h3>未找到题目</h3>
        <p>尝试调整筛选条件或搜索关键词</p>
      </div>`;
    return;
  }

  grid.innerHTML = pageQs.map((q, i) => {
    const typeClass = q.type === '选择题' ? 'choice' : 'nonchoice';
    const typeShort = q.type === '选择题' ? '选择' : '解答';
    const tags = [];
    if (q.sub_questions) tags.push(`${q.sub_questions.length} 个子问`);
    if (q.has_image) tags.push('含图片');
    const statusIcons = statusIconsHtml(q);

    return `
      <div class="question-row" tabindex="0" role="button" aria-label="${q.id} ${q.type}" data-index="${start + i}">
        <span class="row-index">#${start + i + 1}</span>
        <span class="row-type ${typeClass}">${typeShort}</span>
        <div class="row-body">
          <div class="row-content" id="card-text-${start+i}"></div>
          <div class="row-meta">
            <span>${escapeHtml(q.id)}</span>
            <span class="dot"></span>
            <span>第 ${q.page} 页</span>
            <span class="dot"></span>
            <span>${escapeHtml(q.chapter)}</span>
          </div>
        </div>
        <div class="row-tags">
          ${statusIcons ? `<div class="row-status">${statusIcons}</div>` : ''}
          ${tags.map(t => `<span class="row-tag">${t}</span>`).join('')}
        </div>
      </div>
    `;
  }).join('');

  pageQs.forEach((q, i) => {
    const el = document.getElementById(`card-text-${start+i}`);
    if (el) {
      const preview = (!q.content || q.content.startsWith('（本题无主题干') || q.content.trim() === '')
        && q.sub_questions && q.sub_questions.length > 0
          ? q.sub_questions[0]
          : q.content;
      el.textContent = preview;
      renderKatex(el);
      if (search) highlightText(el, search);
    }
  });

  grid.querySelectorAll('[data-fav="1"]').forEach(icon => {
    icon.addEventListener('click', (e) => {
      e.stopPropagation();
      const card = icon.closest('.question-row');
      if (!card) return;
      const idx = Number(card.dataset.index);
      const q = filteredQuestions[idx];
      if (q) toggleFavorite(q);
    });
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
function renderOptionsHtml(q) {
  if (!q.options) return '';
  const opts = Object.entries(q.options).map(([k, v]) => `
    <div class="option-item" data-key="${k}">
      <span class="option-key">${k}.</span>
      <span class="opt-math"></span>
    </div>
  `).join('');
  return `<div class="q-options">${opts}</div>`;
}

function renderSubHtml(q) {
  if (!q.sub_questions) return '';
  return `
    <div class="q-sub">
      <div class="sub-label">子问题</div>
      ${q.sub_questions.map((s, i) => `<div class="sub-item" data-role="sub"></div>`).join('')}
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

function practiceAnswerHtml(q) {
  const isChoice = q.type === '选择题';
  if (isChoice) {
    return `
      <div class="practice-feedback" data-role="practiceFeedback" hidden>
        <div class="feedback-result" data-role="feedbackResult"></div>
        <div class="q-answer-explain" data-role="feedbackExplain"></div>
      </div>
    `;
  }
  return answerHtml(q) + `
    <div class="practice-selfgrade" data-role="selfGrade" hidden>
      <button type="button" class="btn btn-secondary" data-role="markCorrect">我做对了</button>
      <button type="button" class="btn" style="border:1px solid var(--danger);color:var(--danger)" data-role="markWrong">我做错了</button>
    </div>
  `;
}

function bindRevealAnswer(container) {
  const btn = container.querySelector('[data-role="revealBtn"]');
  if (!btn) return;
  btn.onclick = () => {
    const ansBox = container.querySelector('[data-role="ans"]');
    const ansText = container.querySelector('[data-role="qans"]');
    if (!ansBox) return;
    const q = container._q;
    if (q && q.answer) {
      if (ansText && q.answer.explanation) {
        ansText.textContent = q.answer.explanation;
        renderKatex(ansText);
      }
      ansBox.hidden = false;
      btn.parentElement.style.display = 'none';
    }
  };
}

function bindPracticeInteractions(container, q) {
  const isChoice = q.type === '选择题';
  if (isChoice) {
    const opts = container.querySelectorAll('.option-item');
    opts.forEach(opt => {
      opt.addEventListener('click', () => {
        if (container._submitted) return;
        container._submitted = true;
        const selected = opt.dataset.key;
        const correct = q.answer && q.answer.choice;
        const isCorrect = selected === correct;

        opts.forEach(o => {
          o.classList.add('disabled');
          const key = o.dataset.key;
          if (key === correct) o.classList.add('correct');
          if (key === selected && !isCorrect) o.classList.add('wrong');
        });

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
            expl.textContent = '解析：' + q.answer.explanation;
            renderKatex(expl);
          }
        }

        recordPracticeResult(q, isCorrect);
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
    if (markCorrect) markCorrect.onclick = () => { recordPracticeResult(q, true); selfGrade.hidden = true; };
    if (markWrong) markWrong.onclick = () => { recordPracticeResult(q, false); selfGrade.hidden = true; };
  }
}

function recordPracticeResult(q, isCorrect) {
  setStatus(q, isCorrect ? 'correct' : 'wrong');
  const key = questionKey(q);
  const existing = practiceResults.find(r => questionKey(r.q) === key);
  if (existing) existing.correct = isCorrect;
  else practiceResults.push({q, correct: isCorrect});
}

function restorePracticeState(container, q) {
  const key = questionKey(q);
  const record = practiceResults.find(r => questionKey(r.q) === key);
  if (!record) return;

  if (q.type === '选择题') {
    container._submitted = true;
    const correct = q.answer && q.answer.choice;
    const opts = container.querySelectorAll('.option-item');
    opts.forEach(o => {
      o.classList.add('disabled');
      if (o.dataset.key === correct) o.classList.add('correct');
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
        expl.textContent = '解析：' + q.answer.explanation;
        renderKatex(expl);
      }
    }
  } else {
    const btn = container.querySelector('[data-role="revealBtn"]');
    const ansBox = container.querySelector('[data-role="ans"]');
    const ansText = container.querySelector('[data-role="qans"]');
    if (btn) { btn.disabled = true; btn.parentElement.style.display = 'none'; }
    if (ansBox) ansBox.hidden = false;
    if (ansText && q.answer && q.answer.explanation) {
      ansText.textContent = q.answer.explanation;
      renderKatex(ansText);
    }
  }
}

function questionBodyHtml(q, mode) {
  const isPractice = mode === 'practice';
  return `
    ${q.has_image && q.image_ref ? imageHtml(q.image_ref) : ''}
    <div class="q-text" data-role="qtext"></div>
    ${renderOptionsHtml(q)}
    ${renderSubHtml(q)}
    ${isPractice ? practiceAnswerHtml(q) : answerHtml(q)}
  `;
}

function renderQuestionBody(container, q, mode) {
  const qtext = container.querySelector('[data-role="qtext"]');
  if (qtext) { qtext.textContent = q.content; renderKatex(qtext); }

  if (q.options) {
    const optMathEls = container.querySelectorAll('.opt-math');
    const entries = Object.entries(q.options);
    optMathEls.forEach((el, i) => {
      if (entries[i]) { el.textContent = entries[i][1]; renderKatex(el); }
    });
  }

  if (q.sub_questions) {
    const subEls = container.querySelectorAll('[data-role="sub"]');
    q.sub_questions.forEach((s, i) => {
      if (subEls[i]) { subEls[i].textContent = s; renderKatex(subEls[i]); }
    });
  }

  container._q = q;
  if (mode === 'practice') bindPracticeInteractions(container, q);
  else bindRevealAnswer(container);
}

// ========================
// Detail Modal
// ========================
function renderModalContent(q) {
  const container = document.getElementById('modalContent');
  container.innerHTML = `
    <div class="q-chapter">${escapeHtml(q.chapter)} · 第 ${q.page} 页</div>
    <div class="q-id">${escapeHtml(q.id)} <span class="row-type ${q.type === '选择题' ? 'choice' : 'nonchoice'}">${q.type}</span></div>
    ${questionBodyHtml(q)}
  `;
  renderQuestionBody(container, q);
  updateDetailFavoriteButton(q);
}

function updateDetailFavoriteButton(q) {
  const btn = document.getElementById('detailFavoriteBtn');
  if (!btn) return;
  const isFav = getStatus(q) === 'favorite';
  btn.classList.toggle('active', isFav);
  btn.setAttribute('aria-label', isFav ? '取消收藏' : '收藏');
}

function toggleDetailFavorite() {
  if (currentModalIndex < 0 || currentModalIndex >= filteredQuestions.length) return;
  const q = filteredQuestions[currentModalIndex];
  toggleFavorite(q);
  updateDetailFavoriteButton(q);
}

function openDetail(index) {
  currentModalIndex = index;
  renderModalContent(filteredQuestions[index]);
  openModal('detailModal');
}

function closeModal() { closeModalById('detailModal'); }

function prevQuestion() {
  if (currentModalIndex > 0) {
    currentModalIndex--;
    renderModalContent(filteredQuestions[currentModalIndex]);
    document.querySelector('#detailModal .modal-body').scrollTop = 0;
  }
}

function nextQuestion() {
  if (currentModalIndex < filteredQuestions.length - 1) {
    currentModalIndex++;
    renderModalContent(filteredQuestions[currentModalIndex]);
    document.querySelector('#detailModal .modal-body').scrollTop = 0;
  }
}

function imageHtml(imageRef) {
  if (!imageRef) return '';
  const imgPath = imageRef.cropped
    ? imageRef.cropped
    : `../pdf_images/page_${String(imageRef.page).padStart(3, '0')}.png`;
  const note = escapeHtml(imageRef.note);
  return `
    <details class="q-image">
      <summary>查看原图（第 ${imageRef.page} 页）</summary>
      <div class="q-image-content">
        <img src="${imgPath}" alt="第 ${imageRef.page} 页原图" loading="lazy" onerror="this.parentNode.parentNode.style.display='none'" onclick="zoomImage(this.src)">
        <div class="q-image-note">${note} <span style="color:var(--accent)">（点击图片放大）</span></div>
      </div>
    </details>
  `;
}

function zoomImage(src) {
  const overlay = document.createElement('div');
  overlay.className = 'zoom-overlay';
  overlay.onclick = () => overlay.remove();
  const img = document.createElement('img');
  img.src = src;
  overlay.appendChild(img);
  document.body.appendChild(overlay);
}

// ========================
// Practice Mode
// ========================
function startPractice(status) {
  const saved = loadProgress();
  if (saved && saved.ids && saved.ids.length > 0) {
    const choice = confirm(`发现上次未完成的练习（${saved.ids.length} 道题，进度 ${saved.index + 1}/${saved.ids.length}）。\n\n确定 = 继续上次练习\n取消 = 开始新练习`);
    if (choice) {
      if (resumePractice(saved)) return;
    } else {
      clearProgress();
    }
  }

  const type = document.getElementById('typeFilter').value;
  const feature = document.getElementById('featureFilter').value;
  const pool = filterQuestions(allQuestions, {chapter: selectedChapter, type, feature, status: status || activeStatusFilter});

  if (pool.length === 0) {
    const msg = status === 'wrong' ? '还没有错题，先去练习吧' :
                status === 'favorite' ? '还没有收藏题目' :
                '当前筛选条件下没有题目，请先调整筛选条件';
    alert(msg);
    return;
  }

  practiceQueue = shuffleArray([...pool]);
  practiceIndex = 0;
  practiceResults = [];
  practiceFinished = false;
  setPracticeFooter(true);
  saveProgress();
  renderPractice();
  openModal('practiceModal');
}

function setPracticeFooter(visible) {
  const footer = document.querySelector('#practiceModal .modal-footer');
  if (footer) footer.style.display = visible ? 'flex' : 'none';
}

function renderPractice() {
  const q = practiceQueue[practiceIndex];
  const container = document.getElementById('practiceContent');
  const progress = `${practiceIndex + 1} / ${practiceQueue.length}`;

  container.innerHTML = `
    <div class="practice-progress">${escapeHtml(q.chapter)} · ${escapeHtml(q.id)} · ${progress}</div>
    <div class="practice-question">
      <div class="q-id" style="margin-bottom:14px;font-size:0.95rem;color:var(--text-tertiary);font-weight:600;">${q.type} · 第 ${q.page} 页</div>
      ${questionBodyHtml(q, 'practice')}
    </div>
  `;

  renderQuestionBody(container, q, 'practice');
  restorePracticeState(container, q);
  saveProgress();
}

function nextPractice() {
  if (practiceIndex < practiceQueue.length - 1) {
    practiceIndex++;
    renderPractice();
  } else {
    finishPractice();
  }
}

function finishPractice() {
  practiceFinished = true;
  clearProgress();
  const total = practiceResults.length;
  const correct = practiceResults.filter(r => r.correct).length;
  const wrong = total - correct;
  const rate = total ? Math.round(correct / total * 100) : 0;

  const container = document.getElementById('practiceContent');
  container.innerHTML = `
    <div class="practice-summary">
      <h2>练习完成</h2>
      <div class="summary-stats">
        <div class="summary-item"><span>${practiceQueue.length}</span><label>总题数</label></div>
        <div class="summary-item correct"><span>${correct}</span><label>正确</label></div>
        <div class="summary-item wrong"><span>${wrong}</span><label>错误</label></div>
        <div class="summary-item"><span>${rate}%</span><label>正确率</label></div>
      </div>
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

function closePractice() { closeModalById('practiceModal'); }

function prevPractice() {
  if (practiceFinished) return;
  if (practiceIndex > 0) {
    practiceIndex--;
    renderPractice();
  }
}

function resumePractice(saved) {
  const idMap = new Map(allQuestions.map(q => [questionKey(q), q]));
  practiceQueue = saved.ids.map(k => idMap.get(k)).filter(Boolean);
  if (practiceQueue.length === 0) return false;
  practiceIndex = Math.min(saved.index, practiceQueue.length - 1);
  practiceResults = [];
  practiceFinished = false;
  setPracticeFooter(true);
  renderPractice();
  openModal('practiceModal');
  return true;
}

function practiceKey(courseName) {
  // 使用固定前缀 + 课程名，避免 document.title 变化导致进度丢失，同时按课程隔离进度
  return 'mathbank_practice_v1_' + (courseName || getCurrentCourse() || 'default');
}
function saveProgress() { try { localStorage.setItem(practiceKey(), JSON.stringify({ids: practiceQueue.map(questionKey), index: practiceIndex})); } catch(e) {} }
function loadProgress() { try { const r = localStorage.getItem(practiceKey()); return r ? JSON.parse(r) : null; } catch(e) { return null; } }
function clearProgress() { try { localStorage.removeItem(practiceKey()); } catch(e) {} }

function randomQuestion() {
  if (filteredQuestions.length === 0) return;
  let idx = Math.floor(Math.random() * filteredQuestions.length);
  if (filteredQuestions.length > 1 && idx === lastRandomIdx) idx = (idx + 1) % filteredQuestions.length;
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
  document.getElementById('searchInput').addEventListener('input', debounce(resetAndFilter, 200));
  document.getElementById('typeFilter').addEventListener('change', resetAndFilter);
  document.getElementById('featureFilter').addEventListener('change', resetAndFilter);

  document.getElementById('btnPractice').addEventListener('click', () => startPractice());
  document.getElementById('btnRandom').addEventListener('click', randomQuestion);

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
      if (mode === 'wrong') startPractice('wrong');
      else if (mode === 'favorite') startPractice('favorite');
      else startPractice();
    });
    document.addEventListener('click', () => { practiceMenu.hidden = true; });
  }
  document.getElementById('toggleSidebar').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
  });
  document.getElementById('sidebarOverlay').addEventListener('click', () => {
    document.getElementById('sidebar').classList.remove('open');
  });

  const mobileSel = document.getElementById('mobileCourseSelect');
  if (mobileSel) mobileSel.addEventListener('change', (e) => switchCourse(e.target.value));

  function handleCardActivation(e) {
    if (e.type === 'keydown' && e.key !== 'Enter') return;
    const card = e.target.closest('.question-row');
    if (card) openDetail(Number(card.dataset.index));
  }
  document.getElementById('questionGrid').addEventListener('click', handleCardActivation);
  document.getElementById('questionGrid').addEventListener('keydown', handleCardActivation);

  ['detailModal', 'practiceModal'].forEach(id => {
    document.getElementById(id).addEventListener('click', (e) => {
      const opt = e.target.closest('.option-item');
      if (opt) {
        if (opt.closest('#practiceModal')) return;
        const container = opt.closest('.q-options');
        if (container) {
          container.querySelectorAll('.option-item').forEach(o => o.classList.remove('selected'));
          opt.classList.add('selected');
        }
      }
    });
  });

  ['detailModal', 'practiceModal'].forEach(id => {
    document.getElementById(id).addEventListener('click', (e) => {
      if (e.target === e.currentTarget) closeModalById(id);
    });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModalById('detailModal');
      closeModalById('practiceModal');
    }
    const detailActive = document.getElementById('detailModal').classList.contains('active');
    if (detailActive) {
      if (e.key === 'ArrowLeft') { e.preventDefault(); prevQuestion(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); nextQuestion(); }
    }
    const practiceActive = document.getElementById('practiceModal').classList.contains('active');
    if (practiceActive && !practiceFinished) {
      if (e.key === 'ArrowLeft') { e.preventDefault(); prevPractice(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); nextPractice(); }
    }
  });
}

// Initialize
init();
