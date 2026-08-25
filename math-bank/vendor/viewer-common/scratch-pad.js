(function (global) {
  'use strict';
  if (global.ViewerScratchPad && global.ViewerScratchPad.ready) return;

  var ink = global.ViewerScratchInk;
  if (!ink) return;
  var controllers = [];
  var SPLIT_KEY = 'vsp:split';
  var MIN_RATIO = 0.3;
  var MAX_RATIO = 0.85;

  function button(label, className) {
    var element = document.createElement('button');
    element.type = 'button';
    element.className = className;
    element.textContent = label;
    element.setAttribute('aria-label', label);
    return element;
  }

  function isDark() {
    var theme = document.documentElement.getAttribute('data-theme');
    if (theme) return theme === 'dark';
    return global.matchMedia && global.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function stacked() {
    return global.matchMedia && global.matchMedia('(max-width: 767px) and (orientation: portrait)').matches;
  }

  function questionBody(controller) {
    if (controller.kind === 'politics') return document.getElementById('pracBody');
    return controller.split.querySelector('.modal-body');
  }

  function storedRatio() {
    try {
      var raw = global.localStorage.getItem(SPLIT_KEY);
      if (!raw) return null;
      var value = parseFloat(raw);
      if (!isFinite(value)) return null;
      return Math.min(MAX_RATIO, Math.max(MIN_RATIO, value));
    } catch (error) {
      return null;
    }
  }

  function storeRatio(ratio) {
    try {
      global.localStorage.setItem(SPLIT_KEY, String(ratio));
    } catch (error) { /* storage full/blocked: 草稿比例不记忆也不影响使用 */ }
  }

  function clearSplitInline(controller) {
    controller.split.style.gridTemplateColumns = '';
    controller.split.style.gridTemplateRows = '';
    var body = questionBody(controller);
    if (body) body.style.maxHeight = '';
  }

  function applyRatio(controller, ratio) {
    if (ratio == null) return;
    var question = Math.round((1 - ratio) * 1000) / 1000;
    var scratch = Math.round(ratio * 1000) / 1000;
    var body = questionBody(controller);
    if (stacked()) {
      // 竖屏堆叠：改行模板让草稿拿到对应份额，并放开题目区 42dvh 的 CSS 上限。
      controller.split.style.gridTemplateColumns = '';
      if (body) body.style.maxHeight = 'none';
      controller.split.style.gridTemplateRows = controller.kind === 'politics'
        ? 'auto auto minmax(0,' + question + 'fr) auto 8px minmax(140px,' + scratch + 'fr)'
        : 'auto minmax(0,' + question + 'fr) auto 8px minmax(140px,' + scratch + 'fr)';
      return;
    }
    if (body) body.style.maxHeight = '';
    controller.split.style.gridTemplateRows = '';
    controller.split.style.gridTemplateColumns = 'minmax(0,' + question + 'fr) 8px minmax(280px,' + scratch + 'fr)';
  }

  function applyStoredRatio(controller) {
    var ratio = storedRatio();
    if (ratio == null) return;
    applyRatio(controller, ratio);
  }

  function setMaxed(controller, maxed) {
    controller.split.classList.toggle('vsp-max', maxed);
    if (controller.maxBtn) {
      var label = maxed ? '还原' : '放大';
      controller.maxBtn.textContent = label;
      controller.maxBtn.setAttribute('aria-label', label);
      controller.maxBtn.setAttribute('aria-pressed', String(maxed));
    }
  }

  function wireDivider(controller) {
    controller.divider.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) return;
      event.preventDefault();
      var dragging = event.pointerId;
      var lastRatio = null;
      controller.divider.setPointerCapture(dragging);
      controller.divider.classList.add('vsp-dragging');
      var move = function (moveEvent) {
        if (moveEvent.pointerId !== dragging) return;
        moveEvent.preventDefault();
        var rect = controller.split.getBoundingClientRect();
        var vertical = stacked();
        var pos = vertical ? moveEvent.clientY - rect.top : moveEvent.clientX - rect.left;
        var size = vertical ? rect.height : rect.width;
        lastRatio = ink.splitRatio(size, pos, MIN_RATIO, MAX_RATIO);
        applyRatio(controller, lastRatio);
      };
      var up = function (upEvent) {
        if (upEvent.pointerId !== dragging) return;
        controller.divider.classList.remove('vsp-dragging');
        controller.divider.removeEventListener('pointermove', move);
        controller.divider.removeEventListener('pointerup', up);
        controller.divider.removeEventListener('pointercancel', up);
        if (lastRatio != null) storeRatio(lastRatio);
      };
      controller.divider.addEventListener('pointermove', move);
      controller.divider.addEventListener('pointerup', up);
      controller.divider.addEventListener('pointercancel', up);
    });
  }

  function questionId(controller) {
    var question = null;
    if (controller.kind === 'detail') question = global.currentModalQuestion;
    if (controller.kind !== 'detail' && global.practiceQueue) {
      question = global.practiceQueue[global.practiceIndex];
    }
    if (question) {
      if (question.uid) return String(question.uid);
      if (typeof global.questionKey === 'function') return String(global.questionKey(question));
      if (question.id != null) return String(question.id);
    }
    var card = controller.content.querySelector('.q-card[data-uid]');
    if (card) return String(card.getAttribute('data-uid'));
    var text = String(controller.content.textContent || '').replace(/\s+/g, ' ').trim();
    return text ? text.slice(0, 160) : null;
  }

  function active(controller) {
    if (controller.kind !== 'politics') return controller.host.classList.contains('active');
    if (controller.host.classList.contains('active') || controller.host.classList.contains('on')) return true;
    if (global.getComputedStyle(controller.host).display === 'none') return false;
    var visible = Array.prototype.filter.call(document.querySelectorAll('.screen'), function (screen) {
      return global.getComputedStyle(screen).display !== 'none';
    });
    return visible.length === 1 && visible[0] === controller.host;
  }

  function stroke(context, points, tool) {
    if (!points.length) return;
    var style = ink.inkStyle(tool, isDark() ? '#E2E8F0' : '#172033');
    context.globalCompositeOperation = style.composite;
    context.strokeStyle = style.color;
    context.lineWidth = style.width;
    context.lineCap = 'round';
    context.lineJoin = 'round';
    context.beginPath();
    context.moveTo(points[0].x, points[0].y);
    for (var index = 1; index < points.length; index++) context.lineTo(points[index].x, points[index].y);
    if (points.length === 1) context.lineTo(points[0].x + 0.01, points[0].y);
    context.stroke();
  }

  function repaint(controller) {
    var canvas = controller.canvas;
    var rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var ratio = global.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    var context = canvas.getContext('2d');
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, rect.width, rect.height);
    controller.session.replay(rect.width, rect.height).forEach(function (item) {
      stroke(context, item.points, item.tool);
    });
  }

  function close(controller) {
    controller.session.closePad();
    if (controller.split.classList.contains('vsp-split')) controller.split.classList.remove('vsp-split');
    setMaxed(controller, false);
    clearSplitInline(controller);
    if (!controller.panel.hidden) controller.panel.hidden = true;
  }

  function sync(controller) {
    var visible = active(controller);
    if (!visible) {
      if (controller.wasActive) controller.session.reset();
      controller.wasActive = false;
      close(controller);
      return;
    }
    controller.wasActive = true;
    if (controller.session.setQuestion(questionId(controller))) close(controller);
  }

  function setTool(controller, tool) {
    controller.session.tool = tool;
    controller.panel.setAttribute('data-tool', tool);
    controller.pencil.setAttribute('aria-pressed', String(tool === 'pencil'));
    controller.eraser.setAttribute('aria-pressed', String(tool === 'eraser'));
  }

  function wireCanvas(controller) {
    var pointerId = null;
    var previous = null;
    controller.canvas.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) return;
      event.preventDefault();
      pointerId = event.pointerId;
      controller.canvas.setPointerCapture(pointerId);
      var rect = controller.canvas.getBoundingClientRect();
      previous = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      controller.session.begin(ink.toNormPoint(previous.x, previous.y, rect.width, rect.height));
      stroke(controller.canvas.getContext('2d'), [previous], controller.session.tool);
    });
    controller.canvas.addEventListener('pointermove', function (event) {
      if (event.pointerId !== pointerId || !previous) return;
      event.preventDefault();
      var rect = controller.canvas.getBoundingClientRect();
      var point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      controller.session.add(ink.toNormPoint(point.x, point.y, rect.width, rect.height));
      stroke(controller.canvas.getContext('2d'), [previous, point], controller.session.tool);
      previous = point;
    });
    function finish(event) {
      if (event.pointerId !== pointerId) return;
      controller.session.finish();
      pointerId = null;
      previous = null;
    }
    controller.canvas.addEventListener('pointerup', finish);
    controller.canvas.addEventListener('pointercancel', finish);
  }

  function panelFor(controller) {
    var panel = document.createElement('section');
    controller.panel = panel;
    panel.className = 'vsp-panel';
    panel.hidden = true;
    panel.setAttribute('aria-label', '草稿');
    var toolbar = document.createElement('div');
    toolbar.className = 'vsp-toolbar';
    controller.pencil = button('铅笔', 'vsp-tool-btn');
    controller.eraser = button('橡皮', 'vsp-tool-btn');
    var undo = button('撤销', 'vsp-tool-btn');
    var clear = button('清空', 'vsp-tool-btn');
    controller.maxBtn = button('放大', 'vsp-tool-btn');
    controller.maxBtn.setAttribute('aria-pressed', 'false');
    var collapse = button('收起', 'vsp-tool-btn');
    toolbar.append(controller.pencil, controller.eraser, undo, clear, controller.maxBtn, collapse);
    var surface = document.createElement('div');
    surface.className = 'vsp-surface';
    controller.canvas = document.createElement('canvas');
    controller.canvas.className = 'vsp-canvas';
    controller.canvas.setAttribute('aria-label', '草稿画布');
    surface.appendChild(controller.canvas);
    var footer = document.createElement('div');
    footer.className = 'vsp-footer';
    panel.append(toolbar, surface, footer);
    controller.pencil.addEventListener('click', function () { setTool(controller, 'pencil'); });
    controller.eraser.addEventListener('click', function () { setTool(controller, 'eraser'); });
    undo.addEventListener('click', function () { controller.session.undo(); repaint(controller); });
    clear.addEventListener('click', function () { controller.session.clear(); repaint(controller); });
    controller.maxBtn.addEventListener('click', function () {
      setMaxed(controller, !controller.split.classList.contains('vsp-max'));
      repaint(controller);
    });
    collapse.addEventListener('click', function () { close(controller); });
    controller.surface = surface;
    setTool(controller, 'pencil');
    wireCanvas(controller);
    return panel;
  }

  function attach(kind, host, content, header, split) {
    if (!host || !content || !header || host.querySelector('.vsp-open-btn')) return;
    var controller = { kind: kind, host: host, content: content, split: split, session: ink.createSession(), wasActive: false };
    controller.panel = panelFor(controller);
    controller.divider = document.createElement('div');
    controller.divider.className = 'vsp-divider';
    controller.divider.setAttribute('role', 'separator');
    controller.divider.setAttribute('aria-label', '拖拽调整题目与草稿区域比例');
    split.appendChild(controller.divider);
    split.appendChild(controller.panel);
    wireDivider(controller);
    var open = button('草稿', 'vsp-open-btn');
    var anchor = kind === 'politics' ? document.getElementById('pracFav') : header.querySelector('.modal-close');
    header.insertBefore(open, anchor || null);
    open.addEventListener('click', function () {
      sync(controller);
      controller.session.openPad();
      controller.panel.hidden = false;
      controller.split.classList.add('vsp-split');
      applyStoredRatio(controller);
      repaint(controller);
    });
    new MutationObserver(function () { sync(controller); }).observe(host, { attributes: true, attributeFilter: ['class'] });
    new MutationObserver(function () { sync(controller); }).observe(content, { childList: true, subtree: true });
    if (global.ResizeObserver) new ResizeObserver(function () { if (controller.session.open) repaint(controller); }).observe(controller.surface);
    controllers.push(controller);
  }

  function syncAll() {
    controllers.forEach(function (controller) {
      sync(controller);
      if (controller.session.open) {
        applyStoredRatio(controller);
        repaint(controller);
      }
    });
  }

  function wrap(name) {
    var original = global[name];
    if (typeof original !== 'function' || original.__vspWrapped) return;
    function wrapped() {
      var result = original.apply(this, arguments);
      syncAll();
      return result;
    }
    wrapped.__vspWrapped = true;
    global[name] = wrapped;
  }

  function init() {
    var detail = document.getElementById('detailModal');
    var practice = document.getElementById('practiceModal');
    var politics = document.getElementById('screenPractice');
    if (detail) attach('detail', detail, document.getElementById('modalContent'), detail.querySelector('.modal-header-actions') || detail.querySelector('.modal-header'), detail.querySelector('.modal-box'));
    if (practice) attach('practice', practice, document.getElementById('practiceContent'), practice.querySelector('.modal-header'), practice.querySelector('.modal-box'));
    if (politics) attach('politics', politics, document.getElementById('pracBody'), politics.querySelector('.prac-header'), politics);
    ['renderModalContent', 'renderPractice', 'closeModal', 'closePractice', 'showScreen'].forEach(wrap);
    global.addEventListener('resize', syncAll);
    global.addEventListener('orientationchange', syncAll);
    ['pagehide', 'beforeunload'].forEach(function (name) {
      global.addEventListener(name, function () { controllers.forEach(function (controller) { controller.session.reset(); }); });
    });
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      var opened = controllers.find(function (controller) { return controller.session.open; });
      if (!opened) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      close(opened);
    }, true);
    syncAll();
  }

  global.ViewerScratchPad = { ready: true, sync: syncAll };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})(window);
