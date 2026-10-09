'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const signals = require('../static/onboard-signals.js');

test('integrates firmware edges into 20% low duty for active-low PB5', () => {
  const trace = [
    { timeMs: 0, pin: 'PB5', value: 0 },
    { timeMs: 2, pin: 'PB5', value: 1 },
    { timeMs: 10, pin: 'PB5', value: 0 },
    { timeMs: 12, pin: 'PB5', value: 1 }
  ];
  assert.equal(signals.lowDuty(trace, 'board:PB5', 20), 0.2);
  assert.equal(signals.summarize(trace, 20).PB5.lowDuty, 0.2);
});

test('keeps constant HIGH dark and constant LOW fully bright', () => {
  const high = [{ timeMs: 0, pin: 'PE5', value: 1 }];
  const low = [{ timeMs: 0, pin: 'PE5', value: 0 }];
  assert.equal(signals.lowDuty(high, 'PE5', 100), 0);
  assert.equal(signals.brightnessAt(high, 'PE5', 50, 100), 0);
  assert.equal(signals.lowDuty(low, 'PE5', 100), 1);
  assert.equal(signals.brightnessAt(low, 'PE5', 50, 100), 1);
});

test('tracks PB5 and PE5 independently from the same ARM trace', () => {
  const trace = [
    { timeMs: 0, pin: 'PB5', value: 0 },
    { timeMs: 5, pin: 'PB5', value: 1 },
    { timeMs: 0, pin: 'PE5', value: 1 },
    { timeMs: 5, pin: 'PE5', value: 0 }
  ];
  const summary = signals.summarize(trace, 10);
  assert.equal(summary.PB5.lowDuty, 0.5);
  assert.equal(summary.PE5.lowDuty, 0.5);
  assert.equal(signals.valueAt(trace, 'PB5', 2), 0);
  assert.equal(signals.valueAt(trace, 'PE5', 2), 1);
});
