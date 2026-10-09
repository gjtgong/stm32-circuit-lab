'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const data = require('../static/open-board-data.js');
globalThis.OpenBoardData = data;
delete require.cache[require.resolve('../static/open-board-map.js')];
require('../static/open-board-map.js');
const map = globalThis.OpenBoardMap;

test('CAD artifact retains source dimensions and inventory counts', () => {
  assert.equal(data.meta.author, 'PE.JADO');
  assert.equal(data.meta.widthMm, 56.098);
  assert.equal(data.meta.heightMm, 53.5);
  assert.equal(data.pads.length, 385);
  assert.equal(data.tracks.length, 283);
  assert.equal(data.vias.length, 185);
  assert.equal(data.components.length, 54);
  assert.equal(data.graphics.length, 1509);
  assert.deepEqual(data.components.find(component => component.ref === 'U2').padIds.length, 144);
});

test('H1-H9 source pads become pickable wiring endpoints', () => {
  assert.equal(map.holes.length, 124);
  assert.equal(new Set(map.holes.map(hole => hole.header)).size, 9);
  const pb5 = map.holes.find(hole => hole.header === 'H6' && hole.pinNumber === '8');
  assert.ok(pb5);
  assert.equal(pb5.id.startsWith('board:PB5'), true);
  assert.equal(map.normalizeEndpoint(pb5.id), 'board:PB5');
  assert.equal(map.isSupportedGpio('board:PB5'), true);
  assert.equal(map.normalizeGpioEvent('PB5'), 'board:PB5');
  assert.equal(map.endpointForPad(pb5.padId), pb5.id);
});

test('source rail aliases remain unique while normalizing to canonical rails', () => {
  const grounds = map.powerPads.filter(pad => pad.signal === 'GND');
  assert.ok(grounds.length > 0);
  assert.equal(new Set(grounds.map(pad => pad.id)).size, grounds.length);
  assert.ok(grounds.every(pad => map.normalizeEndpoint(pad.id) === 'board:GND'));
});
