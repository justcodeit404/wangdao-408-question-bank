#!/usr/bin/env python3
"""
基于模板生成 math-bank/index.html，改造成三级折叠树：
- L1: 第N章 XXX
- L2: 小节名（可折叠）
- L3: 选择题/解答题（点击筛选）
"""
from pathlib import Path

TEMPLATE = Path('C:/Users/16416/.claude/skills/pdf-to-interactive-bank/references/index.html.template')
OUT = Path('math-bank/index.html')


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = TEMPLATE.read_text(encoding='utf-8')

    # 1. 替换标题占位符
    text = text.replace('__TITLE__', '王道 408·精选题题库')
    text = text.replace('__SIDEBAR_TITLE__', '王道 408·精选题题库')
    text = text.replace('__SIDEBAR_SUBTITLE__', '27 王道考研复习指导')

    # 1.5 在通用 * 之后注入 button reset
    if 'button { font: inherit;' not in text:
        text = text.replace(
            '* { box-sizing: border-box; margin: 0; padding: 0; }\n\nbody {',
            '* { box-sizing: border-box; margin: 0; padding: 0; }\n\nbutton { font: inherit; color: inherit; background: transparent; border: none; cursor: pointer; min-height: 0; height: auto; }\n\nbody {'
        )

    # 2. 在 CSS 部分追加折叠树样式（在 .chapter-item.active .count 后）
    new_css = '''
/* 三级折叠树 */
.tree-toggle {
  display: flex;
  align-items: center;
  width: 100%;
  height: auto !important;
  min-height: 0;
  flex-shrink: 0;
  padding: 7px 10px;
  margin: 1px 0;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.92rem;
  color: var(--text);
  transition: background 0.12s;
  user-select: none;
  border: none;
  background: transparent;
  text-align: left;
  align-self: flex-start;
}
.tree-toggle > span[style*="flex:1"] { min-height: 0; }
.tree-toggle:hover { background: #f3f4f6; }
.tree-toggle .arrow {
  display: inline-block;
  width: 14px;
  text-align: center;
  margin-right: 4px;
  font-size: 0.65rem;
  color: var(--muted);
}
.tree-toggle .count {
  margin-left: auto;
  font-size: 0.72rem;
  color: var(--muted);
  background: #f3f4f6;
  padding: 1px 7px;
  border-radius: 10px;
}
.tree-toggle.active {
  background: #eff6ff !important;
  color: var(--accent);
  font-weight: 500;
}
.tree-toggle.active .count {
  background: #dbeafe;
  color: var(--accent);
}
.tree-l1 {
  font-weight: 600;
  font-size: 0.96rem;
  padding: 9px 10px;
}
.tree-l2-wrap { padding-left: 8px; }
.tree-l2 {
  font-weight: 500;
  color: var(--text);
  padding: 6px 10px;
  font-size: 0.88rem;
}
.tree-l3-wrap { padding-left: 16px; }
.tree-l3 {
  font-weight: 400;
  font-size: 0.82rem;
  color: var(--muted);
  padding: 4px 8px;
}
.tree-l3.choice .arrow { color: var(--success); }
.tree-l3.app .arrow { color: var(--warning); }
.tree-children {
  display: none;
  padding: 1px 0 3px 0;
}
.tree-children.show { display: block; }
.all-item {
  margin-bottom: 4px;
  padding: 8px 10px !important;
}

/* 课程切换 tab */
.course-tabs {
  display: flex;
  gap: 4px;
  padding: 6px 8px 0 8px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-wrap: wrap;
}
.course-tab {
  padding: 6px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--muted);
  border-bottom: 2px solid transparent;
  border-radius: 4px 4px 0 0;
  transition: color 0.12s, border-color 0.12s;
}
.course-tab:hover { color: var(--text); }
.course-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}
.course-tab .cnt {
  margin-left: 4px;
  font-size: 0.7rem;
  color: var(--muted);
  background: #f3f4f6;
  padding: 0 6px;
  border-radius: 8px;
}
.course-tab.active .cnt {
  background: #dbeafe;
  color: var(--accent);
}
'''
    # 插入新css：原模板中 focus-visible CSS 块的结束大括号之后
    insert_marker = '.question-card:focus-visible, .chapter-item:focus-visible, .option-item:focus-visible {\n  outline: 2px solid var(--accent);\n  outline-offset: 2px;\n}'
    if insert_marker in text:
        text = text.replace(insert_marker, insert_marker + '\n' + new_css)
    else:
        # 兼容旧模板
        old_marker = '.chapter-item:focus-visible, .option-item:focus-visible {'
        if old_marker in text:
            text = text.replace(old_marker, new_css + '\n' + old_marker)
        else:
            print('WARN: insert_marker not found')

    # 3. 替换原 renderChapters / selectChapter 为树形
    # 同时修改 init 函数，让每个 q 带 chapterKey
    init_old = '''function init() {
  allQuestions = [];
  bank.chapters.forEach(ch => {
    ch.questions.forEach(q => {
      const entry = {...q, chapter: ch.name};
      entry._searchText = (q.content + ' ' + (q.sub_questions || []).join(' ') + ' ' + ch.name + ' ' + q.id).toLowerCase();
      allQuestions.push(entry);
    });
  });

  renderChapters();
  renderStats();
  applyFilters();
  setupEvents();
}'''
    init_new = '''// 当前选中的课程（默认第一门）
let selectedCourse = '';
// 数据集按当前课程筛选后的缓存
let currentChapters = [];

function getCurrentCourse() {
  const list = bank.courses || [];
  if (!selectedCourse && list.length) selectedCourse = list[0].name;
  return selectedCourse;
}

function getCurrentChapters() {
  const course = getCurrentCourse();
  return bank.chapters.filter(ch => (ch.course || (bank.courses && bank.courses[0] ? bank.courses[0].name : '')) === course);
}

function init() {
  // 渲染顶部课程 tab
  renderCourseTabs();
  currentChapters = getCurrentChapters();
  allQuestions = [];
  currentChapters.forEach(ch => {
    const chapterKey = (ch.l1_name || '?') + '|' + (ch.l2_name || '?') + '|' + (ch.section_type || '?');
    ch.questions.forEach(q => {
      const entry = {...q, chapter: ch.name, chapterKey: chapterKey, course: ch.course || ''};
      entry._searchText = (q.content + ' ' + (q.sub_questions || []).join(' ') + ' ' + ch.name + ' ' + q.id).toLowerCase();
      allQuestions.push(entry);
    });
  });

  renderChapters();
  renderStats();
  applyFilters();
  setupEvents();
}

function renderCourseTabs() {
  const tabsEl = document.getElementById('courseTabs');
  if (!tabsEl) return;
  const list = bank.courses || [];
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

function switchCourse(course) {
  if (course === selectedCourse) return;
  selectedCourse = course;
  selectedChapter = '';
  // 重新过滤
  currentChapters = getCurrentChapters();
  allQuestions = [];
  currentChapters.forEach(ch => {
    const chapterKey = (ch.l1_name || '?') + '|' + (ch.l2_name || '?') + '|' + (ch.section_type || '?');
    ch.questions.forEach(q => {
      const entry = {...q, chapter: ch.name, chapterKey: chapterKey, course: ch.course || ''};
      entry._searchText = (q.content + ' ' + (q.sub_questions || []).join(' ') + ' ' + ch.name + ' ' + q.id).toLowerCase();
      allQuestions.push(entry);
    });
  });
  // 更新 tab 高亮
  document.querySelectorAll('.course-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.course === course);
  });
  currentPage = 1;
  renderChapters();
  renderStats();
  applyFilters();
}'''
    if init_old in text:
        text = text.replace(init_old, init_new)

    # filterQuestions 按 chapterKey 匹配
    filter_old = '''function filterQuestions(source, opts) {
  return source.filter(q => {
    if (opts.chapter && q.chapter !== opts.chapter) return false;'''
    filter_new = '''function filterQuestions(source, opts) {
  return source.filter(q => {
    if (opts.chapter && q.chapterKey !== opts.chapter) return false;'''
    if filter_old in text:
        text = text.replace(filter_old, filter_new)

    old_render = '''function renderChapters() {
  const container = document.getElementById('chapterList');
  container.innerHTML = '';

  const allItem = document.createElement('div');
  allItem.className = 'chapter-item active';
  allItem.innerHTML = `<span>全部章节</span><span class="count">${allQuestions.length}</span>`;
  allItem.onclick = () => selectChapter('');
  container.appendChild(allItem);

  bank.chapters.forEach(ch => {
    const el = document.createElement('div');
    el.className = 'chapter-item';
    el.innerHTML = `<span>${escapeHtml(ch.name)}</span><span class="count">${ch.question_count}</span>`;
    el.onclick = () => selectChapter(ch.name);
    container.appendChild(el);
  });
}

function selectChapter(name) {
  selectedChapter = name;
  document.querySelectorAll('.chapter-item').forEach((el, i) => {
    el.classList.toggle('active', (i === 0 && !name) || (i > 0 && bank.chapters[i-1].name === name));
  });
  currentPage = 1;
  applyFilters();
  if (window.innerWidth <= 768) {
    document.getElementById('sidebar').classList.remove('open');
  }
}'''
    new_render = '''// ========================
// Sidebar - 三级折叠树：L1章节 → L2小节 → L3（选择题 / 解答题）
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

function makeToggle(text, count, extraClass, dataset) {
  const btn = document.createElement('button');
  btn.className = 'tree-toggle ' + (extraClass || '');
  if (dataset) btn.dataset.key = dataset;
  btn.innerHTML = '<span class="arrow">▶</span><span style="flex:1">' + escapeHtml(text) + '</span><span class="count">' + count + '</span>';
  return btn;
}

function renderChapters() {
  const container = document.getElementById('chapterList');
  container.innerHTML = '';

  // 全部章节项（最顶部）
  const allWrap = document.createElement('div');
  const allItem = makeToggle('📚 全部章节', allQuestions.length, 'tree-l1 active all-item', '');
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
      l1Btn.querySelector('.arrow').textContent = exp ? '▼' : '▶';
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
        l2Btn.querySelector('.arrow').textContent = exp ? '▼' : '▶';
      };

      for (const sec of l2Node.sections) {
        const icon = sec.section_type === '选择题' ? '●' : '◆';
        const cls = 'tree-l3 ' + (sec.section_type === '选择题' ? 'choice' : 'app');
        const l3Btn = makeToggle(icon + ' ' + sec.section_type, sec.question_count, cls, sec.key);
        l3Btn.onclick = (e) => {
          e.stopPropagation();
          // 自动展开父级
          l1Btn.classList.add('expanded');
          l1Children.classList.add('show');
          l1Btn.querySelector('.arrow').textContent = '▼';
          l2Btn.classList.add('expanded');
          l2Children.classList.add('show');
          l2Btn.querySelector('.arrow').textContent = '▼';
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
}

function selectChapter(key, btn) {
  selectedChapter = key;
  // 清除所有按钮的active状态
  document.querySelectorAll('.tree-toggle.active').forEach(el => el.classList.remove('active'));
  if (btn) btn.classList.add('active');
  currentPage = 1;
  applyFilters();
  if (window.innerWidth <= 768) {
    document.getElementById('sidebar').classList.remove('open');
  }
}'''
    if old_render in text:
        text = text.replace(old_render, new_render)
    else:
        print('WARN: old renderChapters not found — using substring match')
        # fall back to keyword replacement
        idx = text.find('function renderChapters()')
        end = text.find('// ========================\n// Stats', idx)
        if idx >= 0 and end >= 0:
            text = text[:idx] + new_render + text[end:]

    # 4. 在 sidebar 中插入课程切换 tab 容器（在 chapterList 之前）
    sidebar_marker = '<div class="chapter-list" id="chapterList"></div>'
    tabs_inject = '<div class="course-tabs" id="courseTabs"></div>\n    ' + sidebar_marker
    if sidebar_marker in text:
        text = text.replace(sidebar_marker, tabs_inject, 1)
    else:
        print('WARN: chapterList marker not found for course tabs')

    # 5. 渲染答案：在 questionBodyHtml 增加 q-answer 块，renderQuestionBody 注入文本
    qbody_old = '''function questionBodyHtml(q) {
  return `
    ${q.has_image && q.image_ref ? imageHtml(q.image_ref) : ''}
    <div class="q-text" data-role="qtext"></div>
    ${renderOptionsHtml(q)}
    ${renderSubHtml(q)}
  `;
}'''
    qbody_new = '''function answerHtml(q) {
  const a = q.answer;
  if (!a) return '';
  const choice = a.choice;
  const expl = a.explanation && a.explanation.trim();
  if (!choice && !expl) return '';
  // 默认隐藏:给一个"显示答案"按钮,点击后渲染并显示
  return `
    <div class="q-answer-toggle" data-role="ansToggle">
      <button type="button" class="reveal-answer-btn" data-role="revealBtn">🔒 显示答案</button>
    </div>
    <div class="q-answer" data-role="ans" hidden>
      ${choice ? `<span class="q-answer-choice">答案：${escapeHtml(choice)}</span>` : ''}
      ${expl ? `<div class="q-answer-explain" data-role="qans"></div>` : ''}
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
    // 从父 q 找答案:由调用者 setAnswer 提供
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

function questionBodyHtml(q) {
  return `
    ${q.has_image && q.image_ref ? imageHtml(q.image_ref) : ''}
    <div class="q-text" data-role="qtext"></div>
    ${renderOptionsHtml(q)}
    ${renderSubHtml(q)}
    ${answerHtml(q)}
  `;
}'''
    if qbody_old in text:
        text = text.replace(qbody_old, qbody_new)
    else:
        print('WARN: questionBodyHtml marker not found')

    qrender_old = '''function renderQuestionBody(container, q) {
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
}'''
    qrender_new = '''function renderQuestionBody(container, q) {
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

  // 答案默认隐藏,需要点按钮揭晓
  container._q = q;
  bindRevealAnswer(container);
}'''
    if qrender_old in text:
        text = text.replace(qrender_old, qrender_new)
    else:
        print('WARN: renderQuestionBody marker not found')

    # 6. 在 CSS 中追加 .q-answer 样式
    answer_css = '''
/* 答案块 */
.q-answer-toggle { margin-top: 16px; }
.reveal-answer-btn {
  background: #fff;
  color: var(--accent);
  border: 1px solid var(--accent);
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 0.92rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.reveal-answer-btn:hover { background: var(--accent); color: #fff; }
.reveal-answer-btn:disabled {
  cursor: not-allowed;
  opacity: 0.7;
  background: var(--accent);
  color: #fff;
}
.q-answer {
  margin-top: 16px;
  padding: 12px 14px;
  background: #f0f7ff;
  border-left: 3px solid var(--accent);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
  font-size: 0.95rem;
  color: var(--text);
}
.q-answer[hidden] { display: none; }
.q-answer-choice {
  display: inline-block;
  margin-right: 12px;
  padding: 2px 10px;
  background: var(--accent);
  color: #fff;
  border-radius: 12px;
  font-weight: 600;
  font-size: 0.88rem;
}
.q-answer-explain { margin-top: 8px; }
'''
    css_marker = '/* 三级折叠树 */'
    if css_marker in text and '.q-answer {' not in text:
        text = text.replace(css_marker, answer_css + css_marker, 1)

    OUT.write_text(text, encoding='utf-8')
    print(f'Wrote {OUT}, {OUT.stat().st_size} bytes')


if __name__ == '__main__':
    main()
