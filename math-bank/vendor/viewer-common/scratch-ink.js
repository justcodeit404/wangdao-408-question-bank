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

  return {
    INK_TOOLS: INK_TOOLS,
    isInkTool: isInkTool,
    inkStyle: inkStyle,
    beginStroke: beginStroke,
    addInkPoint: addInkPoint,
    dropLastStroke: dropLastStroke,
    toNormPoint: toNormPoint,
    toCssPoint: toCssPoint,
    createSession: createSession,
  };
});
