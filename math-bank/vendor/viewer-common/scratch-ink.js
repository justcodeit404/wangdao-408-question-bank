(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ViewerScratchInk = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var INK_TOOLS = ['pencil', 'highlighter', 'eraser'];
  var DEFAULT_HIGHLIGHTER = 'rgba(250, 204, 21, 0.42)';
  var PENCIL_WIDTHS = { fine: 1.3, medium: 2.2, bold: 3.8 };
  var HIGHLIGHTER_WIDTHS = { fine: 8, medium: 14, bold: 22 };
  var ERASER_WIDTHS = { fine: 10, medium: 16, bold: 28 };
  var TAP_MAX_MS = 280;
  var TAP_MAX_MOVE_PX = 14;

  function isInkTool(value) {
    return value === 'pencil' || value === 'highlighter' || value === 'eraser';
  }

  function toolWidth(tool, key) {
    if (tool === 'eraser') return ERASER_WIDTHS[key] || 16;
    if (tool === 'highlighter') return HIGHLIGHTER_WIDTHS[key] || 14;
    return PENCIL_WIDTHS[key] || 2.2;
  }

  function inkStyle(tool, ink, appearance) {
    appearance = appearance || {};
    if (tool === 'eraser') return { composite: 'destination-out', color: '#000000', width: appearance.width || 16 };
    if (tool === 'highlighter') {
      return { composite: 'source-over', color: appearance.color || DEFAULT_HIGHLIGHTER, width: appearance.width || 14 };
    }
    return { composite: 'source-over', color: appearance.color || ink, width: appearance.width || 2.2 };
  }

  function withAppearance(stroke, points) {
    var next = { tool: stroke.tool, points: points };
    if (stroke.color) next.color = stroke.color;
    if (stroke.width != null) next.width = stroke.width;
    return next;
  }

  function beginStroke(point, tool, appearance) {
    appearance = appearance || {};
    var stroke = { tool: tool, points: [point] };
    if (appearance.color) stroke.color = appearance.color;
    if (appearance.width != null) stroke.width = appearance.width;
    return stroke;
  }

  function addInkPoint(stroke, point) {
    var last = stroke.points[stroke.points.length - 1];
    if (last && last.x === point.x && last.y === point.y) return stroke;
    return withAppearance(stroke, stroke.points.concat([point]));
  }

  function dropLastStroke(strokes) {
    return strokes.slice(0, -1);
  }

  function toNormPoint(px, py, width, height) {
    return { x: width ? px / width : 0, y: height ? py / height : 0 };
  }

  function toCssPoint(point, width, height) {
    return { x: point.x * width, y: point.y * height };
  }

  // 草稿区分屏占比：草稿位于远端（右/下），占比 = 指针到远端的距离比例，clamp 到 [min, max]。
  function splitRatio(containerSize, pointerPos, min, max) {
    if (!containerSize || containerSize <= 0) return null;
    var lo = typeof min === 'number' ? min : 0.3;
    var hi = typeof max === 'number' ? max : 0.85;
    var ratio = 1 - pointerPos / containerSize;
    if (ratio < lo) return lo;
    if (ratio > hi) return hi;
    return ratio;
  }

  function createSession() {
    var liveStroke = null;
    // Mutable by design: one session accumulates pointer input without replacing UI references.
    var session = {
      questionId: null,
      tool: 'pencil',
      strokes: [],
      open: false,
      _ready: false,
      setQuestion: function (id) {
        if (id === session.questionId) return false;
        session.strokes = [];
        session.redoStack = [];
        session.tool = 'pencil';
        session.open = false;
        session.questionId = id;
        liveStroke = null;
        return true;
      },
      openPad: function () {
        session.open = true;
      },
      closePad: function () {
        session.open = false;
        liveStroke = null;
      },
      reset: function () {
        session.strokes = [];
        session.redoStack = [];
        session.tool = 'pencil';
        session.open = false;
        session.questionId = null;
        liveStroke = null;
      },
      begin: function (point, tool, appearance) {
        liveStroke = beginStroke(point, tool || session.tool, appearance);
        return liveStroke;
      },
      add: function (point) {
        if (!liveStroke) return null;
        liveStroke = addInkPoint(liveStroke, point);
        return liveStroke;
      },
      finish: function () {
        if (!liveStroke) return null;
        session.strokes.push(liveStroke);
        session.redoStack = [];
        var finished = liveStroke;
        liveStroke = null;
        return finished;
      },
      abort: function () {
        liveStroke = null;
      },
      live: function () {
        return liveStroke;
      },
      redoStack: [],
      undo: function () {
        liveStroke = null;
        if (!session.strokes.length) return;
        session.redoStack.push(session.strokes[session.strokes.length - 1]);
        session.strokes = dropLastStroke(session.strokes);
      },
      redo: function () {
        liveStroke = null;
        if (!session.redoStack.length) return;
        session.strokes = session.strokes.concat([session.redoStack.pop()]);
      },
      clearRedo: function () {
        session.redoStack = [];
      },
      clear: function () {
        liveStroke = null;
        session.strokes = [];
        session.redoStack = [];
      },
      replay: function (width, height) {
        return session.strokes.map(function (stroke) {
          return {
            tool: stroke.tool,
            points: stroke.points.map(function (point) {
              return toCssPoint(point, width, height);
            }),
          };
        });
      },
      initOnce: function (flagName) {
        var scope = typeof window !== 'undefined' ? window : globalThis;
        if (scope[flagName]) return false;
        scope[flagName] = true;
        session._ready = true;
        return true;
      },
    };
    return session;
  }

  var PALM_CONTACT_PX = 28;
  var MIN_SCALE = 0.5;
  var MAX_SCALE = 4;
  var IDENTITY_VIEWPORT = { scale: 1, x: 0, y: 0 };

  function clampScale(scale) {
    if (scale < MIN_SCALE) return MIN_SCALE;
    if (scale > MAX_SCALE) return MAX_SCALE;
    return scale;
  }

  function midpoint(a, b) {
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }

  function screenToNorm(sx, sy, width, height, vp) {
    return toNormPoint((sx - vp.x) / vp.scale, (sy - vp.y) / vp.scale, width, height);
  }

  function normToScreen(point, width, height, vp) {
    var css = toCssPoint(point, width, height);
    return { x: css.x * vp.scale + vp.x, y: css.y * vp.scale + vp.y };
  }

  function pinchViewport(vp, prevA, prevB, nextA, nextB) {
    var prevMid = midpoint(prevA, prevB);
    var nextMid = midpoint(nextA, nextB);
    var prevDist = Math.hypot(prevA.x - prevB.x, prevA.y - prevB.y);
    var nextDist = Math.hypot(nextA.x - nextB.x, nextA.y - nextB.y);
    var factor = prevDist > 0 ? nextDist / prevDist : 1;
    var scale = clampScale(vp.scale * factor);
    var used = vp.scale === 0 ? 1 : scale / vp.scale;
    return {
      scale: scale,
      x: nextMid.x - (prevMid.x - vp.x) * used,
      y: nextMid.y - (prevMid.y - vp.y) * used,
    };
  }

  function smoothControlPoints(points) {
    if (points.length < 3) return [];
    var segments = [];
    var from = points[0];
    for (var index = 1; index < points.length - 1; index++) {
      var control = points[index];
      var to = midpoint(control, points[index + 1]);
      segments.push({ from: from, control: control, to: to });
      from = to;
    }
    return segments;
  }

  function clamp01(value) {
    if (value < 0) return 0;
    if (value > 1) return 1;
    return value;
  }

  function samplePenPressure(kind, pressure) {
    if (kind !== 'pen') return null;
    if (!isFinite(pressure) || pressure <= 0) return 0.45;
    return clamp01(Math.max(0.08, pressure));
  }

  function velocityPressure(prev, next) {
    var dist = Math.hypot(next.x - prev.x, next.y - prev.y);
    var t = Math.min(1, dist / 0.04);
    return 0.82 - 0.5 * t;
  }

  function pointPressure(kind, pressure, prev, next) {
    var sampled = samplePenPressure(kind, pressure);
    if (sampled != null) return sampled;
    return prev ? velocityPressure(prev, next) : 0.55;
  }

  function widthFromPressure(base, pressure) {
    var p = isFinite(pressure) ? clamp01(pressure) : 0.55;
    return base * (0.38 + 1.15 * p);
  }

  function withPointPressure(point, pressure) {
    return { x: point.x, y: point.y, p: clamp01(pressure) };
  }

  function isTwoFingerTap(a, b, maxMs, maxMove) {
    maxMs = maxMs == null ? TAP_MAX_MS : maxMs;
    maxMove = maxMove == null ? TAP_MAX_MOVE_PX : maxMove;
    return a.ms <= maxMs && b.ms <= maxMs
      && Math.hypot(a.dx, a.dy) <= maxMove
      && Math.hypot(b.dx, b.dy) <= maxMove;
  }

  function hasVariablePressure(points) {
    for (var i = 0; i < points.length; i++) if (points[i].p != null) return true;
    return false;
  }

  function paintInkPath(ctx, points, style, scale) {
    if (!points.length) return;
    scale = scale || 1;
    ctx.save();
    ctx.globalCompositeOperation = style.composite;
    ctx.strokeStyle = style.color;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    if (points.length === 1 || !hasVariablePressure(points)) {
      var segments = smoothControlPoints(points);
      ctx.lineWidth = style.width * scale;
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      if (points.length === 1) ctx.lineTo(points[0].x + 0.01, points[0].y);
      else if (!segments.length) {
        for (var i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
      } else {
        for (var seg = 0; seg < segments.length; seg++) {
          ctx.quadraticCurveTo(segments[seg].control.x, segments[seg].control.y, segments[seg].to.x, segments[seg].to.y);
        }
        ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);
      }
      ctx.stroke();
      ctx.restore();
      return;
    }
    for (var index = 1; index < points.length; index++) {
      var from = points[index - 1];
      var to = points[index];
      ctx.lineWidth = ((widthFromPressure(style.width, from.p || 0.55) + widthFromPressure(style.width, to.p || 0.55)) / 2) * scale;
      ctx.beginPath();
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.stroke();
    }
    ctx.restore();
  }

  function parsePointerKind(pointerType) {
    if (pointerType === 'pen' || pointerType === 'touch') return pointerType;
    return 'mouse';
  }

  function commitStrokeOnEnd(kind, end) {
    if (end === 'up') return true;
    return kind !== 'pen';
  }

  function resumeLiveStroke(kind, hasLive) {
    return !!hasLive && kind === 'pen';
  }

  var PEN_RESUME_MAX_NORM = 0.08;

  function shouldJoinPenStroke(last, next) {
    if (!last) return false;
    return Math.hypot(last.x - next.x, last.y - next.y) <= PEN_RESUME_MAX_NORM;
  }

  function acceptDrawPointer(pointer, stylusPreferred) {
    if (pointer.kind === 'pen' || pointer.kind === 'mouse') return true;
    return !stylusPreferred && pointer.primary && pointer.contactPx < PALM_CONTACT_PX;
  }

  function prefersStylusByDevice(device) {
    if (/iPad/i.test(device.userAgent)) return true;
    return device.platform === 'MacIntel' && device.maxTouchPoints > 1;
  }

  function parseFingerWriteFlag(raw) {
    if (raw === '1') return true;
    if (raw === '0') return false;
    return null;
  }

  function initialStylusPreferred(device, fingerWrite) {
    if (fingerWrite === true) return false;
    if (fingerWrite === false) return true;
    return prefersStylusByDevice(device);
  }


  // ---- InkDocument v1（三端统一格式）----
  var INK_VERSION = 1;

  function normalizePoint(p) {
    var point = { x: Number(p.x) || 0, y: Number(p.y) || 0 };
    var pressure = Number(p.p);
    if (isFinite(pressure)) point.p = clamp01(pressure);
    return point;
  }

  // 把归一化笔画序列化成 InkDocument v1（platform-v2 / 小程序 可读并恢复书写）。
  function serializeDocument(strokes, width, height, meta) {
    var w = Math.max(1, Math.round(Number(width) || 1));
    var h = Math.max(1, Math.round(Number(height) || 1));
    return {
      version: INK_VERSION,
      width: w,
      height: h,
      aspectRatio: Math.round((h / w) * 1000) / 1000,
      strokes: (strokes || []).map(function (s) {
        var stroke = {
          tool: isInkTool(s && s.tool) ? s.tool : 'pencil',
          points: (s.points || []).map(normalizePoint),
        };
        if (s && s.color) stroke.color = s.color;
        if (s && s.width != null) stroke.width = s.width;
        return stroke;
      }),
      meta: meta || {},
    };
  }

  // 解析 InkDocument v1；非法/空返回 null（可安全降级为空白草稿）。
  function parseDocument(raw) {
    if (!raw || typeof raw !== 'object') return null;
    if (raw.version !== INK_VERSION) return null;
    var strokes = Array.isArray(raw.strokes) ? raw.strokes : [];
    var ok = strokes.every(function (s) {
      return s && isInkTool(s.tool) &&
        Array.isArray(s.points) && s.points.length > 0 &&
        s.points.every(function (p) { return p && isFinite(Number(p.x)) && isFinite(Number(p.y)); });
    });
    if (!ok || !strokes.length) return null;
    var width = Number(raw.width) > 0 ? Number(raw.width) : 1000;
    var height = Number(raw.height) > 0 ? Number(raw.height) : 1000;
    return {
      version: INK_VERSION,
      width: width,
      height: height,
      aspectRatio: Number(raw.aspectRatio) || Math.round((height / width) * 1000) / 1000,
      strokes: strokes.map(function (s) {
        var stroke = { tool: s.tool, points: s.points.map(normalizePoint) };
        if (s.color) stroke.color = s.color;
        if (s.width != null) stroke.width = s.width;
        return stroke;
      }),
      meta: raw.meta || {},
    };
  }

  // 把 InkDocument 画到指定尺寸的 canvas context（白底、高对比；橡皮用白色 source-over 覆盖）。
  function paintDocument(context, doc, outWidth, outHeight, inkColor) {
    var color = inkColor || '#1f2937';
    (doc.strokes || []).forEach(function (stroke) {
      var style = stroke.tool === 'eraser'
        ? { composite: 'source-over', color: '#ffffff', width: stroke.width || 18 }
        : inkStyle(stroke.tool === 'highlighter' ? 'highlighter' : 'pencil', color, { color: stroke.color, width: stroke.width });
      var points = stroke.points.map(function (p) {
        var mapped = { x: p.x * outWidth, y: p.y * outHeight };
        if (p.p != null) mapped.p = p.p;
        return mapped;
      });
      paintInkPath(context, points, style, 1);
    });
  }

  // 导出白底高对比 PNG（限制像素与体积，避免透明背景导致视觉模型识别异常）。
  function documentToPng(doc, maxDim) {
    maxDim = maxDim || 1400;
    var scale = Math.min(1, maxDim / Math.max(doc.width, doc.height));
    var outWidth = Math.max(1, Math.round(doc.width * scale));
    var outHeight = Math.max(1, Math.round(doc.height * scale));
    return new Promise(function (resolve, reject) {
      var canvas = document.createElement('canvas');
      canvas.width = outWidth;
      canvas.height = outHeight;
      var context = canvas.getContext('2d');
      if (!context) return reject(new Error('canvas 不可用'));
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, outWidth, outHeight);
      paintDocument(context, doc, outWidth, outHeight, '#1f2937');
      if (typeof canvas.toBlob === 'function') {
        canvas.toBlob(function (blob) {
          if (blob) resolve(blob);
          else reject(new Error('导出 PNG 失败'));
        }, 'image/png');
        return;
      }
      // 老浏览器兜底：dataURL
      var url = canvas.toDataURL('image/png');
      var bin = atob(url.split(',')[1] || '');
      var arr = new Uint8Array(bin.length);
      for (var idx = 0; idx < bin.length; idx++) arr[idx] = bin.charCodeAt(idx);
      resolve(new Blob([arr], { type: 'image/png' }));
    });
  }

  return {
    INK_TOOLS: INK_TOOLS,
    DEFAULT_HIGHLIGHTER: DEFAULT_HIGHLIGHTER,
    TAP_MAX_MS: TAP_MAX_MS,
    TAP_MAX_MOVE_PX: TAP_MAX_MOVE_PX,
    PALM_CONTACT_PX: PALM_CONTACT_PX,
    MIN_SCALE: MIN_SCALE,
    MAX_SCALE: MAX_SCALE,
    IDENTITY_VIEWPORT: IDENTITY_VIEWPORT,
    isInkTool: isInkTool,
    toolWidth: toolWidth,
    inkStyle: inkStyle,
    beginStroke: beginStroke,
    addInkPoint: addInkPoint,
    dropLastStroke: dropLastStroke,
    toNormPoint: toNormPoint,
    toCssPoint: toCssPoint,
    splitRatio: splitRatio,
    parsePointerKind: parsePointerKind,
    commitStrokeOnEnd: commitStrokeOnEnd,
    resumeLiveStroke: resumeLiveStroke,
    shouldJoinPenStroke: shouldJoinPenStroke,
    acceptDrawPointer: acceptDrawPointer,
    prefersStylusByDevice: prefersStylusByDevice,
    parseFingerWriteFlag: parseFingerWriteFlag,
    initialStylusPreferred: initialStylusPreferred,
    clampScale: clampScale,
    midpoint: midpoint,
    screenToNorm: screenToNorm,
    normToScreen: normToScreen,
    pinchViewport: pinchViewport,
    smoothControlPoints: smoothControlPoints,
    clamp01: clamp01,
    samplePenPressure: samplePenPressure,
    velocityPressure: velocityPressure,
    pointPressure: pointPressure,
    widthFromPressure: widthFromPressure,
    withPointPressure: withPointPressure,
    isTwoFingerTap: isTwoFingerTap,
    paintInkPath: paintInkPath,
    createSession: createSession,
    serializeDocument: serializeDocument,
    parseDocument: parseDocument,
    paintDocument: paintDocument,
    documentToPng: documentToPng,
  };
});
