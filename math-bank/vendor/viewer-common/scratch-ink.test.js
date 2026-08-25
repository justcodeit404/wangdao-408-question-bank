'use strict';

const assert = require('node:assert/strict');
const ink = require('./scratch-ink.js');

function test(name, run) {
  try {
    run();
    console.log('ok - ' + name);
  } catch (error) {
    console.error('not ok - ' + name);
    throw error;
  }
}

try {
  test('begin and add filter duplicate points', function () {
    // Given
    const start = { x: 0.1, y: 0.2 };
    const stroke = ink.beginStroke(start, 'pencil');
    // When
    const duplicate = ink.addInkPoint(stroke, { x: 0.1, y: 0.2 });
    const extended = ink.addInkPoint(duplicate, { x: 0.3, y: 0.4 });
    // Then
    assert.equal(duplicate, stroke);
    assert.deepEqual(extended, { tool: 'pencil', points: [start, { x: 0.3, y: 0.4 }] });
  });

  test('ink styles match pencil and eraser contracts', function () {
    // Given
    const color = '#172033';
    // When
    const pencil = ink.inkStyle('pencil', color);
    const eraser = ink.inkStyle('eraser', color);
    // Then
    assert.deepEqual(pencil, { composite: 'source-over', color, width: 2.2 });
    assert.deepEqual(eraser, { composite: 'destination-out', color: '#000000', width: 16 });
  });

  test('undo and clear remove completed strokes', function () {
    // Given
    const session = ink.createSession();
    session.begin({ x: 0, y: 0 });
    session.finish();
    session.begin({ x: 1, y: 1 });
    session.finish();
    // When
    session.undo();
    // Then
    assert.equal(session.strokes.length, 1);
    session.clear();
    assert.equal(session.strokes.length, 0);
  });

  test('normalized points replay at current canvas scale', function () {
    // Given
    const normalized = ink.toNormPoint(10, 20, 100, 200);
    const session = ink.createSession();
    session.begin(normalized);
    session.finish();
    // When
    const replayed = session.replay(200, 400);
    // Then
    assert.deepEqual(normalized, { x: 0.1, y: 0.1 });
    assert.deepEqual(ink.toCssPoint(normalized, 200, 400), { x: 20, y: 40 });
    assert.deepEqual(replayed[0].points[0], { x: 20, y: 40 });
  });

  test('different question resets strokes and closes pad', function () {
    // Given
    const session = ink.createSession();
    session.setQuestion('q1');
    session.openPad();
    session.begin({ x: 0.2, y: 0.3 });
    session.finish();
    // When
    const reset = session.setQuestion('q2');
    // Then
    assert.equal(reset, true);
    assert.equal(session.questionId, 'q2');
    assert.equal(session.open, false);
    assert.deepEqual(session.strokes, []);
    assert.equal(session.tool, 'pencil');
  });

  test('same question and close reopen preserve strokes', function () {
    // Given
    const session = ink.createSession();
    session.setQuestion('q1');
    session.begin({ x: 0.2, y: 0.3 });
    session.finish();
    session.openPad();
    session.closePad();
    // When
    const reset = session.setQuestion('q1');
    session.openPad();
    // Then
    assert.equal(reset, false);
    assert.equal(session.open, true);
    assert.equal(session.strokes.length, 1);
  });

  test('reset after question switch restores empty defaults', function () {
    // Given
    const session = ink.createSession();
    session.setQuestion('q1');
    session.setQuestion('q2');
    session.tool = 'eraser';
    session.openPad();
    // When
    session.reset();
    // Then
    assert.equal(session.questionId, null);
    assert.equal(session.tool, 'pencil');
    assert.equal(session.open, false);
    assert.deepEqual(session.strokes, []);
  });

  test('splitRatio measures far-edge share with clamping', function () {
    // Given a 1000px split container with the scratch area at the far edge
    // When the divider sits at various pointer positions
    // Then the scratch share is clamped to [0.3, 0.85]
    assert.equal(ink.splitRatio(1000, 500, 0.3, 0.85), 0.5);
    assert.equal(ink.splitRatio(1000, 900, 0.3, 0.85), 0.3);
    assert.equal(ink.splitRatio(1000, 50, 0.3, 0.85), 0.85);
    assert.equal(ink.splitRatio(1000, 0, 0.3, 0.85), 0.85);
    assert.equal(ink.splitRatio(0, 500, 0.3, 0.85), null);
    assert.equal(ink.splitRatio(-10, 500, 0.3, 0.85), null);
    assert.equal(ink.splitRatio(800, 400), 0.5);
  });

  test('initOnce is idempotent across sessions', function () {
    // Given
    const flag = '__viewerScratchInkTestReady';
    delete globalThis[flag];
    const first = ink.createSession();
    const second = ink.createSession();
    // When
    const firstResult = first.initOnce(flag);
    const secondResult = second.initOnce(flag);
    // Then
    assert.equal(firstResult, true);
    assert.equal(secondResult, false);
    assert.equal(first._ready, true);
    assert.equal(second._ready, false);
    delete globalThis[flag];
  });

  test('pointer gate keeps pen and rejects palm while stylus preferred', function () {
    assert.equal(ink.parsePointerKind('pen'), 'pen');
    assert.equal(ink.parsePointerKind(''), 'mouse');
    assert.equal(ink.commitStrokeOnEnd('pen', 'cancel'), false);
    assert.equal(ink.commitStrokeOnEnd('pen', 'up'), true);
    assert.equal(ink.resumeLiveStroke('pen', true), true);
    assert.equal(ink.acceptDrawPointer({ kind: 'pen', contactPx: 2, primary: true }, true), true);
    assert.equal(ink.acceptDrawPointer({ kind: 'touch', contactPx: 8, primary: true }, true), false);
    assert.equal(ink.acceptDrawPointer({ kind: 'touch', contactPx: 40, primary: true }, false), false);
    assert.equal(ink.acceptDrawPointer({ kind: 'touch', contactPx: 8, primary: true }, false), true);
    assert.equal(ink.prefersStylusByDevice({ userAgent: 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)', platform: 'iPad', maxTouchPoints: 5 }), true);
    assert.equal(ink.prefersStylusByDevice({ userAgent: 'Mozilla/5.0', platform: 'Win32', maxTouchPoints: 0 }), false);
    assert.equal(ink.initialStylusPreferred({ userAgent: 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)', platform: 'iPad', maxTouchPoints: 5 }, true), false);
  });

  test('viewport pinch keeps midpoint and smooths polylines', function () {
    const vp = { scale: 2, x: 10, y: 20 };
    const paper = ink.screenToNorm(50, 80, 100, 200, vp);
    assert.deepEqual(paper, { x: 0.2, y: 0.15 });
    assert.deepEqual(ink.normToScreen(paper, 100, 200, vp), { x: 50, y: 80 });
    const pinched = ink.pinchViewport(
      ink.IDENTITY_VIEWPORT,
      { x: 0, y: 40 },
      { x: 100, y: 40 },
      { x: 0, y: 40 },
      { x: 200, y: 40 },
    );
    assert.equal(pinched.scale, 2);
    assert.deepEqual(
      ink.screenToNorm(100, 40, 200, 100, pinched),
      ink.screenToNorm(50, 40, 200, 100, ink.IDENTITY_VIEWPORT),
    );
    assert.deepEqual(ink.midpoint({ x: 0, y: 0 }, { x: 10, y: 0 }), { x: 5, y: 0 });
    assert.deepEqual(
      ink.smoothControlPoints([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }]),
      [{ from: { x: 0, y: 0 }, control: { x: 10, y: 0 }, to: { x: 10, y: 5 } }],
    );
  });

  test('abort drops the live stroke without committing', function () {
    const session = ink.createSession();
    session.begin({ x: 0.2, y: 0.3 });
    session.abort();
    assert.equal(session.live(), null);
    assert.deepEqual(session.strokes, []);
  });
} catch (error) {
  console.error(error);
  process.exitCode = 1;
}
