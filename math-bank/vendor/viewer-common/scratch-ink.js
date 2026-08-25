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
  };
});
