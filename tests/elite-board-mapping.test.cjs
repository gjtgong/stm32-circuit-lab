'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const board = require('../static/board-map.js');
const { evaluate } = require('../static/actuators.js');

function hole(header, pinNumber) {
  const result = board.holes.find(item => item.header === header && item.pinNumber === pinNumber);
  assert.ok(result, `missing ${header}-${pinNumber}`);
  return result;
}

test('V1 physical holes expose 106 P1/P2 GPIOs plus P3/P5 and omit RTC pins', () => {
  const main = board.holes.filter(item => (item.header === 'P1' || item.header === 'P2') && item.kind === 'gpio');
  assert.equal(main.length, 106);
  assert.equal(board.auxiliary.length, 4);
  assert.equal(board.gpioIds.length, 110);
  assert.equal(board.gpioIds.includes('board:PC14'), false);
  assert.equal(board.gpioIds.includes('board:PC15'), false);
  assert.equal(board.endpointIds.includes('board:PB0'), true);
  assert.equal(board.endpointIds.includes('board:GND'), true);
});

test('photo orientation follows odd-right/even-left and bottom pin 1', () => {
  const p2One = hole('P2', 1);
  const p2Two = hole('P2', 2);
  const p1One = hole('P1', 1);
  const p1Two = hole('P1', 2);
  assert.equal(p2One.signal, 'PB8');
  assert.equal(p2Two.signal, 'PB7');
  assert.equal(p1One.signal, 'PE0');
  assert.equal(p1Two.signal, 'PB9');
  assert.ok(p2One.nativeX > p2Two.nativeX);
  assert.ok(p1One.nativeX > p1Two.nativeX);
  assert.equal(hole('P2', 53).signal, 'PB12');
  assert.equal(hole('P2', 54).signal, 'GND');
  assert.equal(hole('P1', 53).signal, 'GND');
  assert.equal(hole('P1', 54).signal, 'PB11');
  assert.ok(p2One.nativeY > hole('P2', 53).nativeY);
});

test('auxiliary and power pads use documented physical header positions', () => {
  assert.deepEqual(board.auxiliary.map(item => `${item.header}-${item.pinNumber}:${item.signal}`), [
    'P3-1:PA10', 'P3-3:PA9', 'P5-1:PA2', 'P5-2:PA3'
  ]);
  assert.equal(board.powerPads.length, 12);
  assert.deepEqual(board.powerPads.filter(item => item.header === 'VOUT2').map(item => item.signal), [
    'GND', '5V', 'GND', '5V', 'GND', '5V'
  ]);
  assert.equal(board.normalizeEndpoint('board:GND:VOUT1-2'), 'board:GND');
  assert.equal(board.normalizeEndpoint('board:5V:VOUT2-3'), 'board:5V');
  assert.equal(board.normalizeEndpoint('board:3V3:VOUT1-3'), 'board:3V3');
  const primaryGround = board.powerPads.find(item => item.id === 'board:GND');
  assert.equal(primaryGround.header, 'VOUT2');
  assert.equal(primaryGround.nativeY, 252);
});

test('actuator graph canonicalizes duplicate power pads while keeping legacy rails', () => {
  const result = evaluate({
    parts: [{ id: 's1', type: 'servo' }],
    wires: [
      { a: 's1:V+', b: 'board:5V:VOUT2-2', color: '#50c9ef' },
      { a: 's1:GND', b: 'board:GND:VOUT1-2', color: '#50c9ef' },
      { a: 's1:PWM', b: 'board:PA0', color: '#50c9ef' }
    ],
    events: [
      { timeMs: 0, pin: 'PA0', value: 1 },
      { timeMs: 1.5, pin: 'board:PA0', value: 0 }
    ],
    durationMs: 20
  });
  assert.equal(result.outputs[0].status, 'active');
  assert.deepEqual(result.outputs[0].samples.map(sample => sample.angleDeg), [90]);
});
