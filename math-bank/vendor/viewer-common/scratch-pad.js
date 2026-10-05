(function (global) {
  'use strict';
  if (global.ViewerScratchPad && global.ViewerScratchPad.ready) return;

  var ink = global.ViewerScratchInk;
  if (!ink) return;
  var controllers = [];
  var SPLIT_KEY = 'vsp:split';
  var FINGER_KEY = 'scratch:finger-write';
  var PREFS_KEY = 'vsp:prefs';
  var PENCIL_COLORS = ['#1C1917', '#1D4ED8', '#BE123C', '#047857'];
  var HIGHLIGHTER_COLORS = ['rgba(250, 204, 21, 0.42)', 'rgba(74, 222, 128, 0.38)', 'rgba(244, 114, 182, 0.38)', 'rgba(96, 165, 250, 0.38)'];
  var WIDTH_KEYS = ['fine', 'medium', 'bold'];
  var MIN_RATIO = 0.3;
  var MAX_RATIO = 0.85;

  function readFingerWrite() {
    try {
      return ink.parseFingerWriteFlag(global.localStorage.getItem(FINGER_KEY));
    } catch (error) {
      return null;
    }
  }

  function storeFingerWrite(fingerWrite) {
    try {
      global.localStorage.setItem(FINGER_KEY, fingerWrite ? '1' : '0');
    } catch (error) {
      return;
    }
  }

  function loadPrefs() {
    try {
      var raw = JSON.parse(global.localStorage.getItem(PREFS_KEY) || '');
      var color = PENCIL_COLORS.indexOf(raw.color) >= 0 ? raw.color : PENCIL_COLORS[0];
      var hlColor = HIGHLIGHTER_COLORS.indexOf(raw.hlColor) >= 0 ? raw.hlColor : HIGHLIGHTER_COLORS[0];
      var widthKey = WIDTH_KEYS.indexOf(raw.widthKey) >= 0 ? raw.widthKey : 'medium';
      return { color: color, hlColor: hlColor, widthKey: widthKey };
    } catch (error) {
      return { color: PENCIL_COLORS[0], hlColor: HIGHLIGHTER_COLORS[0], widthKey: 'medium' };
    }
  }

  function storePrefs(prefs) {
    try { global.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (error) { /* quota */ }
  }

  function resolvedPencilColor(color) {
    if (color === PENCIL_COLORS[0] && isDark()) return '#E2E8F0';
    return color;
  }

  function appearanceFor(tool, prefs) {
    if (tool === 'highlighter') return { color: prefs.hlColor, width: ink.toolWidth(tool, prefs.widthKey) };
    if (tool === 'eraser') return { width: ink.toolWidth(tool, prefs.widthKey) };
    return { color: resolvedPencilColor(prefs.color), width: ink.toolWidth(tool, prefs.widthKey) };
  }

  function loadStylusPreferred() {
    return ink.initialStylusPreferred({
      userAgent: global.navigator ? global.navigator.userAgent : '',
      platform: global.navigator ? global.navigator.platform : '',
      maxTouchPoints: global.navigator ? global.navigator.maxTouchPoints || 0 : 0,
    }, readFingerWrite());
  }

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

  function hostQuestion(controller) {
    if (typeof global.getActiveQuestion === 'function') {
      try {
        var active = global.getActiveQuestion();
        if (active) return active;
      } catch (error) { /* host getter optional */ }
    }
    if (controller.kind === 'detail' && typeof global.getCurrentDetailQuestion === 'function') {
      try { return global.getCurrentDetailQuestion(); } catch (error) { /* optional */ }
    }
    if (controller.kind === 'detail') return global.currentModalQuestion || null;
    if (global.practiceQueue) return global.practiceQueue[global.practiceIndex] || null;
    return null;
  }

  function contentUid(controller) {
    var el = controller.content.querySelector('[data-uid]');
    if (!el) return null;
    return el.getAttribute('data-uid');
  }

  function questionMeta(controller) {
    var question = hostQuestion(controller);
    var uid = ink.resolveQuestionUid({
      question: question,
      questionKey: global.questionKey,
      contentUid: contentUid(controller),
    });
    var chapter = '', title = '';
    if (question) {
      if (question.chapter) chapter = String(question.chapter);
      if (question.title) title = String(question.title);
    }
    if (!title) {
      var text = String(controller.content.textContent || '').replace(/\s+/g, ' ').trim();
      if (text) title = text.slice(0, 160);
    }
    return { uid: uid, chapter: chapter, title: title };
  }

  function questionId(controller) {
    return questionMeta(controller).uid;
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

  function resetViewport(controller) {
    controller.viewport = { scale: 1, x: 0, y: 0 };
  }

  function paperToScreen(points, width, height, vp) {
    return points.map(function (point) {
      var screen = ink.normToScreen(point, width, height, vp);
      if (point.p == null) return screen;
      return { x: screen.x, y: screen.y, p: point.p };
    });
  }

  function stroke(context, item, scale) {
    var style = ink.inkStyle(item.tool, isDark() ? '#E2E8F0' : '#172033', { color: item.color, width: item.width });
    ink.paintInkPath(context, item.points, style, scale || 1);
  }

  function rebuildCommitted(controller, rect, dpr) {
    var canvas = controller.canvas;
    var layer = controller.committed || document.createElement('canvas');
    controller.committed = layer;
    layer.width = canvas.width;
    layer.height = canvas.height;
    var ctx = layer.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    var vp = controller.viewport || ink.IDENTITY_VIEWPORT;
    controller.session.strokes.forEach(function (item) {
      stroke(ctx, {
        tool: item.tool,
        color: item.color,
        width: item.width,
        points: paperToScreen(item.points, rect.width, rect.height, vp),
      }, vp.scale);
    });
  }

  function blitDisplay(controller, rect, dpr) {
    var canvas = controller.canvas;
    var ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (controller.committed) ctx.drawImage(controller.committed, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var live = controller.session.live();
    if (!live) {
      controller.liveDrawn = 0;
      return;
    }
    var vp = controller.viewport || ink.IDENTITY_VIEWPORT;
    stroke(ctx, {
      tool: live.tool,
      color: live.color,
      width: live.width,
      points: paperToScreen(live.points, rect.width, rect.height, vp),
    }, vp.scale);
    controller.liveDrawn = live.points.length;
  }

  function repaint(controller, mode) {
    var canvas = controller.canvas;
    var rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var fitted = ink.fitCanvas(canvas, rect.width, rect.height, global.devicePixelRatio || 1);
    if (mode !== 'live' || fitted.resized || !controller.committed) {
      rebuildCommitted(controller, rect, fitted.dpr);
    }
    blitDisplay(controller, rect, fitted.dpr);
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
      if (controller.wasActive) {
        // 关闭弹层/切屏同切题一样不丢未保存笔迹（question-notes.js 挂的钩子，脏检查入队）
        if (typeof controller.beforeQuestionChange === 'function') controller.beforeQuestionChange();
        controller.session.reset();
        resetViewport(controller);
      }
      controller.wasActive = false;
      close(controller);
      return;
    }
    controller.wasActive = true;
    var nextUid = questionId(controller);
    if (controller.session.questionId !== nextUid) {
      // 切题前先持久化未保存笔迹（viewer-common question-notes.js 挂的钩子）
      if (typeof controller.beforeQuestionChange === 'function') controller.beforeQuestionChange();
    }
    var wasOpen = controller.session.open;
    if (controller.session.setQuestion(nextUid)) {
      resetViewport(controller);
      controller.committed = null;
      if (wasOpen) {
        controller.session.openPad();
        repaint(controller);
      } else {
        close(controller);
      }
      // 草稿板开着时切题：清上一题结果并回显本题已保存笔记（question-notes.js 挂的钩子）
      if (controller.session.open && typeof controller.afterQuestionChange === 'function') controller.afterQuestionChange();
    }
  }

  function setTool(controller, tool) {
    controller.session.tool = tool;
    controller.panel.setAttribute('data-tool', tool);
    controller.pencil.setAttribute('aria-pressed', String(tool === 'pencil'));
    if (controller.highlighter) controller.highlighter.setAttribute('aria-pressed', String(tool === 'highlighter'));
    controller.eraser.setAttribute('aria-pressed', String(tool === 'eraser'));
    syncSwatches(controller);
  }

  function syncSwatches(controller) {
    var tool = controller.session.tool;
    var colors = tool === 'highlighter' ? HIGHLIGHTER_COLORS : PENCIL_COLORS;
    var active = tool === 'highlighter' ? controller.prefs.hlColor : controller.prefs.color;
    if (controller.colorRow) {
      controller.colorRow.hidden = tool === 'eraser';
      Array.prototype.forEach.call(controller.colorRow.querySelectorAll('.vsp-color'), function (dot, index) {
        dot.style.background = colors[index].indexOf('rgba') === 0 ? colors[index].replace(/[\d.]+\)$/, '1)') : colors[index];
        dot.setAttribute('aria-pressed', String(colors[index] === active));
        dot.dataset.color = colors[index];
      });
    }
    if (controller.widthRow) {
      Array.prototype.forEach.call(controller.widthRow.querySelectorAll('.vsp-width'), function (btn) {
        btn.setAttribute('aria-pressed', String(btn.dataset.width === controller.prefs.widthKey));
      });
    }
  }

  function localPoint(canvas, event) {
    var rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top, width: rect.width, height: rect.height };
  }

  function asDrawPointer(event) {
    return {
      kind: ink.parsePointerKind(event.pointerType),
      contactPx: Math.max(event.width || 0, event.height || 0),
      primary: event.isPrimary !== false,
    };
  }

  function touchPointerIds(pointers) {
    return Object.keys(pointers).filter(function (id) {
      return pointers[id].kind === 'touch';
    }).map(Number);
  }

  function wireCanvas(controller) {
    var pointers = Object.create(null);
    var fingerMeta = Object.create(null);
    var drawingId = null;
    var drawingKind = null;
    var pinchPair = null;

    function abortDraw() {
      drawingId = null;
      drawingKind = null;
      controller.session.abort();
      repaint(controller);
    }

    function startPinch() {
      var ids = touchPointerIds(pointers);
      if (ids.length < 2) return;
      pinchPair = [ids[0], ids[1]];
      if (drawingKind !== 'pen') abortDraw();
    }

    function beginStyled(paper) {
      controller.session.begin(paper, controller.session.tool, appearanceFor(controller.session.tool, controller.prefs));
    }

    function adoptDraw(event, local) {
      var kind = ink.parsePointerKind(event.pointerType);
      var paper = ink.screenToNorm(local.x, local.y, local.width, local.height, controller.viewport);
      var live = controller.session.live();
      var last = live && live.points.length ? live.points[live.points.length - 1] : null;
      paper = ink.withPointPressure(paper, ink.pointPressure(kind, event.pressure, last, paper));
      if (ink.resumeLiveStroke(kind, !!live)) {
        drawingId = event.pointerId;
        drawingKind = kind;
        if (ink.shouldJoinPenStroke(last, paper)) controller.session.add(paper);
        else {
          controller.session.finish();
          beginStyled(paper);
        }
        return;
      }
      if (drawingId != null) return;
      if (!ink.acceptDrawPointer(asDrawPointer(event), controller.stylusPreferred)) return;
      drawingId = event.pointerId;
      drawingKind = kind;
      beginStyled(paper);
    }

    function appendSamples(event) {
      var rect = controller.canvas.getBoundingClientRect();
      var kind = ink.parsePointerKind(event.pointerType);
      var batch = typeof event.getCoalescedEvents === 'function' ? event.getCoalescedEvents() : [];
      if (!batch.length) batch = [event];
      for (var index = 0; index < batch.length; index++) {
        var sample = batch[index];
        var paper = ink.screenToNorm(
          sample.clientX - rect.left,
          sample.clientY - rect.top,
          rect.width,
          rect.height,
          controller.viewport,
        );
        var live = controller.session.live();
        var last = live && live.points.length ? live.points[live.points.length - 1] : null;
        controller.session.add(ink.withPointPressure(paper, ink.pointPressure(kind, sample.pressure, last, paper)));
      }
    }

    controller.canvas.addEventListener('touchstart', function (event) { event.preventDefault(); }, { passive: false });
    controller.canvas.addEventListener('touchmove', function (event) { event.preventDefault(); }, { passive: false });
    controller.canvas.addEventListener('pointerdown', function (event) {
      event.preventDefault();
      if (event.button !== 0) return;
      controller.canvas.setPointerCapture(event.pointerId);
      var local = localPoint(controller.canvas, event);
      pointers[event.pointerId] = { x: local.x, y: local.y, kind: ink.parsePointerKind(event.pointerType) };
      if (ink.parsePointerKind(event.pointerType) === 'touch') {
        fingerMeta[event.pointerId] = { x: local.x, y: local.y, t: Date.now(), moved: false };
      }
      if (touchPointerIds(pointers).length >= 2) {
        startPinch();
        return;
      }
      adoptDraw(event, local);
      repaint(controller);
    });
    controller.canvas.addEventListener('pointermove', function (event) {
      event.preventDefault();
      var kind = ink.parsePointerKind(event.pointerType);
      var local = localPoint(controller.canvas, event);
      var current = pointers[event.pointerId];
      if (!current && ink.resumeLiveStroke(kind, !!controller.session.live())) {
        try { controller.canvas.setPointerCapture(event.pointerId); } catch (error) { /* capture optional after iOS cancel */ }
        current = { x: local.x, y: local.y, kind: kind };
        pointers[event.pointerId] = current;
        drawingId = event.pointerId;
        drawingKind = kind;
      }
      if (!current) return;
      var previous = { x: current.x, y: current.y };
      current.x = local.x;
      current.y = local.y;
      var meta = fingerMeta[event.pointerId];
      if (meta && Math.hypot(local.x - meta.x, local.y - meta.y) > ink.TAP_MAX_MOVE_PX) meta.moved = true;
      if (pinchPair && (event.pointerId === pinchPair[0] || event.pointerId === pinchPair[1])) {
        var first = pointers[pinchPair[0]];
        var second = pointers[pinchPair[1]];
        var metaA = fingerMeta[pinchPair[0]];
        var metaB = fingerMeta[pinchPair[1]];
        if (!first || !second) return;
        if (!metaA || !metaB || (!metaA.moved && !metaB.moved)) return;
        var prevA = event.pointerId === pinchPair[0] ? previous : first;
        var prevB = event.pointerId === pinchPair[1] ? previous : second;
        controller.viewport = ink.pinchViewport(controller.viewport, prevA, prevB, first, second);
        repaint(controller);
        return;
      }
      if (event.pointerId !== drawingId) return;
      appendSamples(event);
      repaint(controller, 'live');
    });
    function endPointer(event) {
      var kind = pointers[event.pointerId] ? pointers[event.pointerId].kind : drawingKind;
      var liftedMeta = fingerMeta[event.pointerId];
      delete pointers[event.pointerId];
      if (pinchPair && (event.pointerId === pinchPair[0] || event.pointerId === pinchPair[1])) {
        var otherId = event.pointerId === pinchPair[0] ? pinchPair[1] : pinchPair[0];
        var otherMeta = fingerMeta[otherId];
        var otherDown = pointers[otherId];
        if (!otherDown && liftedMeta && otherMeta && !liftedMeta.moved && !otherMeta.moved) {
          var now = Date.now();
          if (ink.isTwoFingerTap({ dx: 0, dy: 0, ms: now - liftedMeta.t }, { dx: 0, dy: 0, ms: now - otherMeta.t })) {
            controller.session.undo();
          }
          delete fingerMeta[pinchPair[0]];
          delete fingerMeta[pinchPair[1]];
          pinchPair = null;
        }
        if (touchPointerIds(pointers).length >= 2) startPinch();
      } else {
        delete fingerMeta[event.pointerId];
      }
      if (event.pointerId !== drawingId) return;
      var end = event.type === 'pointercancel' ? 'cancel' : 'up';
      if (!ink.commitStrokeOnEnd(kind || 'mouse', end)) {
        drawingId = null;
        return;
      }
      controller.session.finish();
      drawingId = null;
      drawingKind = null;
      repaint(controller);
    }
    controller.canvas.addEventListener('pointerup', endPointer);
    controller.canvas.addEventListener('pointercancel', endPointer);
    controller.canvas.addEventListener('lostpointercapture', function (event) {
      if (event.pointerId !== drawingId || drawingKind !== 'pen') return;
      try { controller.canvas.setPointerCapture(event.pointerId); } catch (error) { /* iOS may refuse recapture until next down */ }
    });
  }

  function isolateToolbar(controller, toolbar) {
    toolbar.addEventListener('selectstart', function (event) { event.preventDefault(); });
    toolbar.addEventListener('pointerdown', function (event) {
      // 工具栏始终可用：无视「仅笔」设置放行正常手指点按，只拦手掌级触摸（否则 iPad 默认仅笔模式下所有按钮手指点不动）
      if (ink.acceptDrawPointer(asDrawPointer(event), false)) return;
      controller.blockToolClick = true;
      event.preventDefault();
      event.stopPropagation();
    }, true);
    toolbar.addEventListener('click', function (event) {
      if (!controller.blockToolClick) return;
      controller.blockToolClick = false;
      event.preventDefault();
      event.stopPropagation();
    }, true);
  }

  function panelFor(controller) {
    var panel = document.createElement('section');
    controller.panel = panel;
    panel.className = 'vsp-panel';
    panel.hidden = true;
    panel.setAttribute('aria-label', '草稿');
    resetViewport(controller);
    var toolbar = document.createElement('div');
    toolbar.className = 'vsp-toolbar';
    controller.prefs = loadPrefs();
    controller.pencil = button('铅笔', 'vsp-tool-btn');
    controller.highlighter = button('荧光笔', 'vsp-tool-btn');
    controller.eraser = button('橡皮', 'vsp-tool-btn');
    var undo = button('撤销', 'vsp-tool-btn');
    var redo = button('重做', 'vsp-tool-btn');
    var clear = button('清空', 'vsp-tool-btn');
    controller.maxBtn = button('放大', 'vsp-tool-btn');
    controller.maxBtn.setAttribute('aria-pressed', 'false');
    controller.penOnly = button('仅笔', 'vsp-tool-btn');
    var collapse = button('收起', 'vsp-tool-btn');
    controller.colorRow = document.createElement('div');
    controller.colorRow.className = 'vsp-swatches';
    PENCIL_COLORS.forEach(function (color, index) {
      var dot = document.createElement('button');
      dot.type = 'button';
      dot.className = 'vsp-color';
      dot.setAttribute('aria-label', '颜色' + (index + 1));
      controller.colorRow.appendChild(dot);
      dot.addEventListener('click', function () {
        if (controller.session.tool === 'highlighter') controller.prefs.hlColor = dot.dataset.color;
        else controller.prefs.color = dot.dataset.color;
        storePrefs(controller.prefs);
        syncSwatches(controller);
      });
    });
    controller.widthRow = document.createElement('div');
    controller.widthRow.className = 'vsp-swatches';
    WIDTH_KEYS.forEach(function (key) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'vsp-width';
      btn.dataset.width = key;
      btn.setAttribute('aria-label', key === 'fine' ? '细笔' : key === 'medium' ? '中笔' : '粗笔');
      btn.innerHTML = '<span></span>';
      controller.widthRow.appendChild(btn);
      btn.addEventListener('click', function () {
        controller.prefs.widthKey = key;
        storePrefs(controller.prefs);
        syncSwatches(controller);
      });
    });
    toolbar.append(controller.pencil, controller.highlighter, controller.eraser, controller.colorRow, controller.widthRow, controller.penOnly, undo, redo, clear, controller.maxBtn, collapse);
    var surface = document.createElement('div');
    surface.className = 'vsp-surface';
    controller.canvas = document.createElement('canvas');
    controller.canvas.className = 'vsp-canvas';
    controller.canvas.setAttribute('aria-label', '草稿画布');
    surface.appendChild(controller.canvas);
    var footer = document.createElement('div');
    footer.className = 'vsp-footer';
    controller.footer = footer;
    panel.append(toolbar, surface, footer);
    if (global.ViewerQuestionNotes && global.ViewerQuestionNotes.ready) {
      global.ViewerQuestionNotes.init(controller);
    }
    isolateToolbar(controller, toolbar);
    panel.addEventListener('selectstart', function (event) { event.preventDefault(); });
    controller.stylusPreferred = loadStylusPreferred();
    controller.penOnly.setAttribute('aria-pressed', String(controller.stylusPreferred));
    controller.penOnly.setAttribute('aria-label', '仅触控笔书写');
    controller.pencil.addEventListener('click', function () { setTool(controller, 'pencil'); });
    controller.highlighter.addEventListener('click', function () { setTool(controller, 'highlighter'); });
    controller.eraser.addEventListener('click', function () { setTool(controller, 'eraser'); });
    controller.penOnly.addEventListener('click', function () {
      controller.stylusPreferred = !controller.stylusPreferred;
      controller.penOnly.setAttribute('aria-pressed', String(controller.stylusPreferred));
      storeFingerWrite(!controller.stylusPreferred);
    });
    undo.addEventListener('click', function () { controller.session.undo(); repaint(controller); });
    redo.addEventListener('click', function () { controller.session.redo(); repaint(controller); });
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
    // 供 question-notes.js 回显笔迹后重绘画布
    controller.repaint = function (mode) { repaint(controller, mode); };
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
      // 打开草稿板时回显本题已保存笔记（question-notes.js 挂的钩子）
      if (typeof controller.afterQuestionChange === 'function') controller.afterQuestionChange();
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
    ['renderModalContent', 'renderPractice', 'nextPractice', 'prevPractice', 'closeModal', 'closePractice', 'showScreen'].forEach(wrap);
    global.addEventListener('resize', syncAll);
    global.addEventListener('orientationchange', syncAll);
    ['pagehide', 'beforeunload'].forEach(function (name) {
      global.addEventListener(name, function () {
        controllers.forEach(function (controller) {
          // 关页同切题：未保存笔迹先入队再 reset，不静默丢原稿
          if (typeof controller.beforeQuestionChange === 'function') controller.beforeQuestionChange();
          controller.session.reset();
        });
      });
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

  global.ViewerScratchPad = { ready: true, sync: syncAll, questionMeta: questionMeta };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})(window);
