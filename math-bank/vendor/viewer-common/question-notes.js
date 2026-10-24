(function (global) {
  'use strict';
  if (global.ViewerQuestionNotes && global.ViewerQuestionNotes.ready) return;

  var ink = global.ViewerScratchInk;
  if (!ink) return;

  var QUEUE_KEY = 'vn:notes:queue';
  var QUEUE_VERSION = 1;
  var MAX_QUEUE = 200;
  var NOTE_PREFIX = 'vn:note:';          // 幂等键前缀 note:{bank}:{uid}

  // ---- 平台 / 登录 / 管理员探测 ----

  function onPlatformHost() {
    return !!(global.ViewerPlatformSync && global.ViewerPlatformSync.onPlatformHost
      && global.ViewerPlatformSync.onPlatformHost());
  }

  function bankKey() {
    if (global.VIEWER_BANK_KEY) return String(global.VIEWER_BANK_KEY);
    if (global.BANK_KEY) return String(global.BANK_KEY);
    try {
      var tab = document.querySelector('.shell-tab.active');
      if (tab && tab.getAttribute('data-bank')) return String(tab.getAttribute('data-bank'));
    } catch (e) { /* noop */ }
    return '';
  }

  // ---- 队列（本地持久化；平台挂载 + 登录后自动补传，幂等不重复建笔记）----

  function readQueue() {
    try {
      var raw = global.localStorage.getItem(QUEUE_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  // ponytail: 队列超限不再截断——截断即静默丢未同步原稿。localStorage 全库上限约 5-10MB，
  // 墨迹 JSON 体积大，真正根治需迁 IndexedDB；当前用徽标 + console.warn 提醒及时同步止损。
  var queueBadgeEl = null;

  function updateQueueBadge() {
    if (!queueBadgeEl) return;
    var n = readQueue().length;
    queueBadgeEl.hidden = n === 0;
    queueBadgeEl.textContent = n > 0 ? '本地暂存 ' + n + ' 条未同步笔记，请打开学习平台同步' : '';
  }

  function writeQueue(entries) {
    if (entries.length > MAX_QUEUE) {
      console.warn('[viewer-notes] 本地暂存队列已达 ' + entries.length + ' 条（告警阈值 ' + MAX_QUEUE + '），未截断；请尽快打开学习平台同步');
    }
    try {
      global.localStorage.setItem(QUEUE_KEY, JSON.stringify(entries));
    } catch (e) {
      console.warn('[viewer-notes] 本地存储空间不足，笔记暂存失败，即将丢失数据：' + e);
    }
    updateQueueBadge();
  }

  function queueKey(meta) {
    return NOTE_PREFIX + String(meta.bank || '') + ':' + String(meta.uid || '');
  }

  var revisionPrefix = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  var revisionSeq = 0;

  function enqueue(meta, doc) {
    var entries = readQueue();
    var key = queueKey(meta);
    var existing = entries.find(function (it) { return it.key === key; });
    var entry = { key: key, version: QUEUE_VERSION, bank: meta.bank, source_uid: meta.uid, chapter: meta.chapter, title: meta.title, ink_document: doc, created_at: Date.now(), revision: revisionPrefix + '-' + (++revisionSeq) };
    if (existing) entries.splice(entries.indexOf(existing), 1, entry);
    else entries.push(entry);
    writeQueue(entries);
    return entry;
  }

  function sameRevision(a, b) {
    if (!a || !b || a.key !== b.key) return false;
    if (a.revision != null || b.revision != null) return a.revision === b.revision;
    return a.created_at === b.created_at;
  }

  function dropQueue(entry) {
    writeQueue(readQueue().filter(function (it) { return !sameRevision(it, entry); }));
  }

  var entryLocks = Object.create(null);

  function withEntryLock(entry, task) {
    var previous = entryLocks[entry.key] || Promise.resolve();
    var result = previous.then(task);
    var tail = result.then(function () {}, function () {});
    entryLocks[entry.key] = tail;
    tail.then(function () {
      if (entryLocks[entry.key] === tail) delete entryLocks[entry.key];
    });
    return result;
  }

  // ---- 远程调用 ----

  function api(path, opts, auth) {
    opts = opts || {};
    var headers = {};
    if (auth && auth.token) headers.Authorization = 'Bearer ' + auth.token;
    var init = { method: opts.method || 'GET', credentials: 'include', headers: headers };
    if (opts.body != null) {
      init.body = opts.body;
      if (!(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    }
    return fetch(path, init).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { /* 非 JSON */ }
        return { status: res.status, ok: res.ok, data: data };
      });
    });
  }

  function resolveRemote(meta, auth) {
    return api('/api/notes/resolve-question', {
      method: 'POST',
      body: JSON.stringify({ bank: meta.bank, source_uid: meta.uid, chapter: meta.chapter || '', title: meta.title || '' }),
    }, auth);
  }

  function saveRemote(meta, doc, imageBlob, auth) {
    var form = new FormData();
    form.append('ink_document', JSON.stringify(doc));
    form.append('image', imageBlob, 'note.jpg');
    return api('/api/notes/question/' + encodeURIComponent(meta.questionId) + '/save', { method: 'POST', body: form }, auth);
  }

  function getRemote(questionId, auth) {
    return api('/api/notes/question/' + encodeURIComponent(questionId), {}, auth);
  }

  function recognizeRemote(questionId, confirm, auth) {
    return api('/api/notes/question/' + encodeURIComponent(questionId) + '/recognize', {
      method: 'POST',
      body: JSON.stringify({ confirm: !!confirm }),
    }, auth);
  }

  function updateMarkdownRemote(questionId, markdown, auth) {
    return api('/api/notes/question/' + encodeURIComponent(questionId) + '/markdown', {
      method: 'PUT',
      body: JSON.stringify({ recognized_markdown: markdown }),
    }, auth);
  }

  function deleteRemote(questionId, auth) {
    return api('/api/notes/question/' + encodeURIComponent(questionId), { method: 'DELETE' }, auth);
  }

  // ---- 保存主流程（先原稿，后识别；失败不丢原稿）----

  async function ensureAuthed() {
    var sync = global.ViewerPlatformSync;
    if (!sync || !sync.ensureAuth) return { ok: false, token: null };
    return sync.ensureAuth();
  }

  function currentDoc(controller) {
    return ink.serializeDocument(controller.session.strokes, controller.canvas.width || 800, controller.canvas.height || 600, { source: 'viewer' });
  }

  // 返回 { ok, queued?, saved?, note?, adminOnly?, status?, error? }
  async function saveNote(controller, opts) {
    opts = opts || {};
    var recognize = !!opts.recognize;
    var meta = (global.ViewerScratchPad && global.ViewerScratchPad.questionMeta
      ? global.ViewerScratchPad.questionMeta(controller)
      : null) || {};
    if (!meta.uid) return { ok: false, error: '缺少题目 UID，无法保存笔记' };
    meta.bank = meta.bank || bankKey();
    var doc = currentDoc(controller);
    // 记录已持久化笔迹签名，切题/关闭时据此脏检查，避免重复入队已同步内容
    controller.lastNoteStrokesSig = JSON.stringify(doc.strokes);
    var entry = enqueue(meta, doc);

    if (!onPlatformHost()) {
      return { ok: true, queued: true, message: '独立题库：已暂存本地，从平台 /banks/ 打开后自动补存' };
    }
    return withEntryLock(entry, async function () {
      var auth = await ensureAuthed();
      if (!auth.ok) {
        return { ok: true, queued: true, message: '未登录：已暂存本地，登录平台后自动补存' };
      }

      var resolved = await resolveRemote(meta, auth);
      if (!resolved.ok) {
        // 未解析到平台题目：仍保留原稿到本地队列，避免数据未导入时丢失
        return { ok: true, queued: true, message: '暂未在平台解析到该题，已暂存本地' };
      }
      meta.questionId = resolved.data.question_id;
      var image = await ink.documentToPng(doc, 1400, 'image/jpeg', 0.85);
      var saved = await saveRemote(meta, doc, image, auth);
      if (!saved.ok) {
        if (recognize && saved.status === 403) {
          return { ok: false, status: 403, error: '无权限保存笔记' };
        }
        return { ok: true, queued: true, message: '网络异常：已暂存本地，联网后自动补存' };
      }
      dropQueue(entry);
      var note = saved.data;

      if (recognize) {
        var rec = await recognizeRemote(note.question_id, false, auth);
        if (rec.status === 403 || rec.status === 401) {
          return { ok: true, saved: true, note: note, adminOnly: true, error: '已保存原稿，自动识别仅管理员可用' };
        }
        if (!rec.ok) {
          return { ok: true, saved: true, note: note, status: rec.status, error: (rec.data && rec.data.detail) || ('识别失败：HTTP ' + rec.status) };
        }
        note = rec.data;
      }
      return { ok: true, saved: true, note: note };
    });
  }

  // 补传队列：只保存原稿（识别由用户后续显式触发，避免覆盖人工内容）。
  // ponytail: 3 并发 worker；同题按序保存避免反序覆盖，不同题仍并发；失败条目保留重试。
  async function flushQueue() {
    if (!onPlatformHost()) return { ok: false, sent: 0 };
    var auth = await ensureAuthed();
    if (!auth.ok) return { ok: false, sent: 0 };
    var entries = readQueue();
    if (!entries.length) return { ok: true, sent: 0 };
    var remain = [];
    var succeeded = [];
    var sent = 0;
    var next = 0;
    async function worker() {
      while (next < entries.length) {
        var entry = entries[next++];
        var meta = { bank: entry.bank || '', uid: entry.source_uid, chapter: entry.chapter, title: entry.title };
        try {
          await withEntryLock(entry, async function () {
            var current = readQueue().some(function (it) { return sameRevision(it, entry); });
            if (!current) return;
            var resolved = await resolveRemote(meta, auth);
            if (!resolved.ok) throw new Error('resolve 404');
            meta.questionId = resolved.data.question_id;
            var doc = ink.parseDocument(entry.ink_document) || entry.ink_document;
            var image = await ink.documentToPng(doc, 1400, 'image/jpeg', 0.85);
            var saved = await saveRemote(meta, doc, image, auth);
            if (!saved.ok) throw new Error('save HTTP ' + saved.status);
            succeeded.push(entry);
            sent++;
          });
        } catch (e) {
          remain.push(entry);
        }
      }
    }
    await Promise.all([worker(), worker(), worker()]);
    var pending = readQueue().filter(function (it) {
      return !succeeded.some(function (entry) { return sameRevision(it, entry); });
    });
    writeQueue(pending);
    return { ok: remain.length === 0, sent: sent, pending: pending.length };
  }

  // ---- UI：保存按钮 + 状态 + 结果面板 ----

  function button(label, className, aria) {
    var el = document.createElement('button');
    el.type = 'button';
    el.className = className;
    el.textContent = label;
    el.setAttribute('aria-label', aria || label);
    return el;
  }

  function statusOf(note) {
    if (!note) return 'none';
    return note.recognition_status || 'none';
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // 简单 Markdown + KaTeX 渲染（模型输出必须转义后再进 DOM，禁止未消毒输出）
  function renderMarkdown(markdown) {
    var text = String(markdown == null ? '' : markdown);
    var blocks = [];
    var re = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;
    var last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) blocks.push({ t: 'text', v: text.slice(last, m.index) });
      blocks.push({ t: 'math', v: m[1] != null ? m[1] : m[2] });
      last = re.lastIndex;
    }
    if (last < text.length) blocks.push({ t: 'text', v: text.slice(last) });
    return blocks.map(function (b) {
      if (b.t === 'math') {
        if (global.katex && global.katex.renderToString) {
          try { return global.katex.renderToString(b.v, { throwOnError: false, displayMode: false }); }
          catch (e) { return escapeHtml('$' + b.v + '$'); }
        }
        return escapeHtml('$' + b.v + '$');
      }
      return escapeHtml(b.v).replace(/\n/g, '<br>');
    }).join('');
  }

  function buildNoteUI(controller) {
    var wrap = document.createElement('div');
    wrap.className = 'vn-note';
    var queueBadge = document.createElement('div');
    queueBadge.className = 'vn-queue-badge';
    queueBadge.hidden = true;
    queueBadgeEl = queueBadge;
    updateQueueBadge();
    var actions = document.createElement('div');
    actions.className = 'vn-actions';
    var saveBtn = button('保存原稿', 'vsp-tool-btn vn-save', '保存笔记原稿');
    var recognizeBtn = button('保存并识别', 'vsp-tool-btn vn-recognize', '保存并识别笔记');
    actions.append(saveBtn, recognizeBtn);
    var status = document.createElement('div');
    status.className = 'vn-status';
    status.hidden = true;
    var result = document.createElement('div');
    result.className = 'vn-result';
    result.hidden = true;
    wrap.append(queueBadge, actions, status, result);

    function setStatus(text, isError) {
      status.hidden = false;
      status.textContent = text;
      status.classList.toggle('vn-error', !!isError);
    }

    function renderResult(note, adminOnly) {
      result.hidden = false;
      result.innerHTML = '';
      if (adminOnly) {
        var hint = document.createElement('div');
        hint.className = 'vn-admin-hint';
        hint.textContent = '已保存原稿，自动识别仅管理员可用';
        result.appendChild(hint);
      }
      if (!note) return;
      var row = document.createElement('div');
      row.className = 'vn-row';
      if (note.image_url) {
        var img = document.createElement('img');
        img.className = 'vn-thumb';
        img.alt = '笔记原稿';
        img.loading = 'lazy';
        img.src = note.image_url;
        row.appendChild(img);
      }
      var badge = document.createElement('span');
      var st = statusOf(note);
      badge.className = 'vn-badge vn-badge-' + st;
      badge.textContent = st === 'success' ? '已识别' : st === 'failed' ? '识别失败' : st === 'recognizing' ? '识别中' : '已保存原稿';
      row.appendChild(badge);
      result.appendChild(row);

      var md = document.createElement('div');
      md.className = 'vn-md';
      if (note.recognized_markdown) md.innerHTML = renderMarkdown(note.recognized_markdown);
      else md.textContent = note.recognition_status === 'failed' ? '（识别失败，可重试）' : '（尚无转写稿）';
      result.appendChild(md);

      var area = document.createElement('textarea');
      area.className = 'vn-textarea';
      area.rows = 6;
      area.hidden = true;
      area.value = note.recognized_markdown || '';
      result.appendChild(area);

      var ops = document.createElement('div');
      ops.className = 'vn-ops';
      var edit = button('编辑', 'vsp-tool-btn', '编辑转写稿');
      var done = button('完成', 'vsp-tool-btn vn-hidden', '保存转写稿编辑');
      var retry = button('重新识别', 'vsp-tool-btn', '重新识别转写稿');
      var del = button('删除', 'vsp-tool-btn vn-danger', '删除这条笔记');
      ops.append(edit, done, retry, del);
      result.appendChild(ops);

      edit.addEventListener('click', function () {
        area.hidden = false;
        edit.hidden = true;
        done.hidden = false;
        md.hidden = true;
        area.focus();
      });
      done.addEventListener('click', async function () {
        done.disabled = true;
        var auth = await ensureAuthed();
        if (!auth.ok) { setStatus('未登录，无法保存编辑', true); done.disabled = false; return; }
        var res = await updateMarkdownRemote(note.question_id, area.value, auth);
        done.disabled = false;
        if (!res.ok) { setStatus('保存编辑失败：' + ((res.data && res.data.detail) || 'HTTP ' + res.status), true); return; }
        area.hidden = true;
        edit.hidden = false;
        done.hidden = true;
        md.hidden = false;
        note = res.data;
        md.innerHTML = renderMarkdown(note.recognized_markdown);
        setStatus('已保存转写稿');
      });
      retry.addEventListener('click', async function () {
        retry.disabled = true;
        setStatus('识别中…');
        var auth = await ensureAuthed();
        if (!auth.ok) { setStatus('未登录，无法识别', true); retry.disabled = false; return; }
        var res = await recognizeRemote(note.question_id, true, auth);
        retry.disabled = false;
        if (res.status === 403 || res.status === 401) { setStatus('自动识别仅管理员可用', true); return; }
        if (!res.ok) { setStatus((res.data && res.data.detail) || ('识别失败：HTTP ' + res.status), true); return; }
        note = res.data;
        md.innerHTML = renderMarkdown(note.recognized_markdown);
        renderResult(note, false);
        setStatus('识别完成');
      });
      del.addEventListener('click', async function () {
        if (!global.confirm || !global.confirm('删除这条题目笔记？')) return;
        var auth = await ensureAuthed();
        if (!auth.ok) { setStatus('未登录，无法删除', true); return; }
        var res = await deleteRemote(note.question_id, auth);
        if (!res.ok) { setStatus('删除失败：' + ((res.data && res.data.detail) || 'HTTP ' + res.status), true); return; }
        result.hidden = true;
        setStatus('已删除笔记');
      });
    }

    async function doSave(recognize) {
      saveBtn.disabled = true;
      recognizeBtn.disabled = true;
      setStatus(recognize ? '保存并识别中…' : '保存中…');
      var out = await saveNote(controller, { recognize: recognize });
      saveBtn.disabled = false;
      recognizeBtn.disabled = false;
      if (!out.ok) { setStatus(out.error || '保存失败', true); return; }
      if (out.queued) { setStatus(out.message || '已暂存本地'); return; }
      if (out.adminOnly) { renderResult(out.note, true); setStatus('已保存原稿，自动识别仅管理员可用', false); return; }
      if (out.note) renderResult(out.note, false);
      if (out.status === 502 || out.status === 503) setStatus(out.error || '识别未启用', true);
      else if (out.status && out.status !== 200) setStatus(out.error || '识别失败', true);
      else setStatus('已保存' + (recognize ? '并识别' : '原稿'));
    }

    saveBtn.addEventListener('click', function () { doSave(false); });
    recognizeBtn.addEventListener('click', function () { doSave(true); });
    return { wrap: wrap, doSave: doSave, setStatus: setStatus, renderResult: renderResult, result: result, status: status };
  }

  var IMPORT_CHUNK = 100;

  function normalizeTextItem(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var markdown = String(raw.markdown || '').trim();
    if (!markdown) return null;
    var bank = String(raw.bank || '').trim();
    if (!bank) return null;
    return {
      bank: bank.slice(0, 32),
      source_uid: String(raw.source_uid || '').slice(0, 256),
      chapter: String(raw.chapter || '').slice(0, 256),
      title: String(raw.title || '').slice(0, 2000),
      markdown: markdown.slice(0, 20000),
    };
  }

  async function importTextNotes(rawItems) {
    if (!onPlatformHost()) return { ok: false, saved: 0, skipped: 0, unresolved: 0 };
    var auth = await ensureAuthed();
    if (!auth.ok) return { ok: false, saved: 0, skipped: 0, unresolved: 0 };
    var items = [];
    var source = Array.isArray(rawItems) ? rawItems : [];
    for (var i = 0; i < source.length; i++) {
      var item = normalizeTextItem(source[i]);
      if (item) items.push(item);
    }
    if (!items.length) return { ok: true, saved: 0, skipped: 0, unresolved: 0 };
    var saved = 0, skipped = 0, unresolved = 0;
    for (var offset = 0; offset < items.length; offset += IMPORT_CHUNK) {
      var chunk = items.slice(offset, offset + IMPORT_CHUNK);
      var res = await api('/api/notes/import-text', {
        method: 'POST',
        body: JSON.stringify({ items: chunk }),
      }, auth);
      if (!res.ok || !res.data) return { ok: false, saved: saved, skipped: skipped, unresolved: unresolved, status: res.status };
      saved += Number(res.data.saved) || 0;
      skipped += Number(res.data.skipped) || 0;
      unresolved += Number(res.data.unresolved) || 0;
    }
    return { ok: true, saved: saved, skipped: skipped, unresolved: unresolved };
  }

  // ---- 回显：切题 / 打开草稿板后，拉取本题已保存笔记（笔迹回放到画布 + 转写稿渲染）----

  async function hydrate(controller, ui) {
    if (!onPlatformHost()) return;
    var meta = (global.ViewerScratchPad && global.ViewerScratchPad.questionMeta
      ? global.ViewerScratchPad.questionMeta(controller)
      : null) || {};
    if (!meta.uid) return;
    meta.bank = meta.bank || bankKey();
    // 同题且画布已有笔迹（已回显过，或用户在回显基础上又画过）时不重复拉取
    if (controller.hydratedFor === meta.uid && controller.session.strokes.length) return;
    var token = (controller.hydrateToken = (controller.hydrateToken || 0) + 1);
    var auth = await ensureAuthed();
    if (!auth.ok || token !== controller.hydrateToken) return;
    var resolved = await resolveRemote(meta, auth);
    if (!resolved.ok || token !== controller.hydrateToken) return;
    var got = await getRemote(resolved.data.question_id, auth);
    if (token !== controller.hydrateToken) return;
    if (!got.ok || !got.data) return; // 404 = 本题尚无笔记，保持空白即可
    var note = got.data;
    controller.hydratedFor = meta.uid;
    var doc = ink.parseDocument(note.ink_document);
    if (doc && doc.strokes.length) {
      controller.session.strokes = doc.strokes;
      controller.session.redoStack = [];
      controller.lastNoteStrokesSig = JSON.stringify(currentDoc(controller).strokes);
      if (controller.session.open && typeof controller.repaint === 'function') controller.repaint();
    }
    ui.renderResult(note, false);
  }

  function init(controller) {
    if (!controller || controller.noteUI) return;
    var ui = buildNoteUI(controller);
    controller.noteUI = ui;
    if (controller.footer) controller.footer.appendChild(ui.wrap);

    // 切题 / 收起 / 关页前不静默丢弃未保存笔迹：与上次保存/回显一致的原稿不再重复入队
    controller.beforeQuestionChange = function () {
      if (!controller.session || !controller.session.strokes || !controller.session.strokes.length) return;
      var meta = (global.ViewerScratchPad && global.ViewerScratchPad.questionMeta
        ? global.ViewerScratchPad.questionMeta(controller)
        : null) || {};
      if (!meta.uid) return;
      meta.bank = meta.bank || bankKey();
      var doc = currentDoc(controller);
      if (JSON.stringify(doc.strokes) === controller.lastNoteStrokesSig) return;
      doc.meta = { source: 'viewer', auto: true };
      enqueue(meta, doc);
    };

    // 切题 / 打开草稿板后：清掉上一题结果面板，回显本题已保存笔记
    controller.afterQuestionChange = function () {
      controller.lastNoteStrokesSig = null;
      ui.result.hidden = true;
      ui.result.innerHTML = '';
      ui.status.hidden = true;
      hydrate(controller, ui);
    };
  }

  global.ViewerQuestionNotes = {
    ready: true,
    init: init,
    saveNote: saveNote,
    flushQueue: flushQueue,
    queueKey: queueKey,
    bankKey: bankKey,
    renderMarkdown: renderMarkdown,
    enqueue: enqueue,
    readQueue: readQueue,
    updateQueueBadge: updateQueueBadge,
    importTextNotes: importTextNotes,
  };

  // 平台挂载模式下打开时自动补传本地暂存
  try { if (onPlatformHost()) setTimeout(function () { flushQueue(); }, 600); } catch (e) { /* noop */ }
})(typeof window !== 'undefined' ? window : globalThis);
