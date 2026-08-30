(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ViewerScratchInk = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var INK_TOOLS = ['pencil', 'eraser'];

  function isInkTool(value) {
    return value === 'pencil' || value === 'eraser';
  }

  function inkStyle(tool, ink) {
    return tool === 'eraser'
      ? { composite: 'destination-out', color: '#000000', width: 16 }
      : { composite: 'source-over', color: ink, width: 2.2 };
  }

  function beginStroke(point, tool) {
    return { tool: tool, points: [point] };
  }

  function addInkPoint(stroke, point) {
    var last = stroke.points[stroke.points.length - 1];
    if (last && last.x === point.x && last.y === point.y) return stroke;
    return { tool: stroke.tool, points: stroke.points.concat([point]) };
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
        session.tool = 'pencil';
        session.open = false;
        session.questionId = null;
        liveStroke = null;
      },
      begin: function (point) {
        liveStroke = beginStroke(point, session.tool);
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
      undo: function () {
        liveStroke = null;
        session.strokes = dropLastStroke(session.strokes);
      },
      clear: function () {
        liveStroke = null;
        session.strokes = [];
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
    return { x: Number(p.x) || 0, y: Number(p.y) || 0 };
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
        return {
          tool: isInkTool(s && s.tool) ? s.tool : 'pencil',
          points: (s.points || []).map(normalizePoint),
        };
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
      return s && (s.tool === 'pencil' || s.tool === 'eraser') &&
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
        return { tool: s.tool, points: s.points.map(normalizePoint) };
      }),
      meta: raw.meta || {},
    };
  }

  // 把 InkDocument 画到指定尺寸的 canvas context（白底、高对比；橡皮用白色 source-over 覆盖）。
  function paintDocument(context, doc, outWidth, outHeight, inkColor) {
    var color = inkColor || '#1f2937';
    (doc.strokes || []).forEach(function (stroke) {
      var style = stroke.tool === 'eraser'
        ? { composite: 'source-over', color: '#ffffff', width: 18 }
        : { composite: 'source-over', color: color, width: 2.2 };
      var points = stroke.points.map(function (p) { return { x: p.x * outWidth, y: p.y * outHeight }; });
      var segments = smoothControlPoints(points);
      context.save();
      context.globalCompositeOperation = style.composite;
      context.strokeStyle = style.color;
      context.lineWidth = style.width;
      context.lineCap = 'round';
      context.lineJoin = 'round';
      context.beginPath();
      context.moveTo(points[0].x, points[0].y);
      if (points.length === 1) {
        context.lineTo(points[0].x + 0.01, points[0].y);
      } else if (!segments.length) {
        for (var i = 1; i < points.length; i++) context.lineTo(points[i].x, points[i].y);
      } else {
        for (var seg = 0; seg < segments.length; seg++) {
          context.quadraticCurveTo(segments[seg].control.x, segments[seg].control.y, segments[seg].to.x, segments[seg].to.y);
        }
        var last = points[points.length - 1];
        context.lineTo(last.x, last.y);
      }
      context.stroke();
      context.restore();
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
    PALM_CONTACT_PX: PALM_CONTACT_PX,
    MIN_SCALE: MIN_SCALE,
    MAX_SCALE: MAX_SCALE,
    IDENTITY_VIEWPORT: IDENTITY_VIEWPORT,
    isInkTool: isInkTool,
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
    createSession: createSession,
    serializeDocument: serializeDocument,
    parseDocument: parseDocument,
    paintDocument: paintDocument,
    documentToPng: documentToPng,
  };
});
