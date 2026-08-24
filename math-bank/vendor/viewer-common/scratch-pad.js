(function (global) {
  'use strict';
  if (global.ViewerScratchPad && global.ViewerScratchPad.ready) return;

  var ink = global.ViewerScratchInk;
  if (!ink) return;
  var controllers = [];

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
    var collapse = button('收起', 'vsp-tool-btn');
    toolbar.append(controller.pencil, controller.eraser, undo, clear, collapse);
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
    split.appendChild(controller.panel);
    var open = button('草稿', 'vsp-open-btn');
    var anchor = kind === 'politics' ? document.getElementById('pracFav') : header.querySelector('.modal-close');
    header.insertBefore(open, anchor || null);
    open.addEventListener('click', function () {
      sync(controller);
      controller.session.openPad();
      controller.panel.hidden = false;
      controller.split.classList.add('vsp-split');
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
      if (controller.session.open) repaint(controller);
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
