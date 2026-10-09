'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { evaluate } = require('../static/actuators.js');

function wire(a, b) {
  return { a, b, color: '#50c9ef' };
}

function outputFor(result, id) {
  const output = result.outputs.find(item => item.partId === id);
  assert.ok(output, `missing actuator output for ${id}`);
  return output;
}

function poweredServo() {
  return {
    parts: [{ id: 's1', type: 'servo' }],
    wires: [
      wire('s1:V+', 'board:5V'),
      wire('s1:GND', 'board:GND'),
      wire('s1:PWM', 'board:PA0')
    ]
  };
}

function poweredDriver() {
  return {
    parts: [{ id: 'd1', type: 'driver' }],
    wires: [
      wire('d1:VM', 'board:5V'),
      wire('d1:VCC', 'board:3V3'),
      wire('d1:GND', 'board:GND'),
      wire('d1:STBY', 'board:PA0'),
      wire('d1:AIN1', 'board:PA1'),
      wire('d1:AIN2', 'board:PA2'),
      wire('d1:PWMA', 'board:PA3'),
      wire('d1:STBY', 'board:PB0'),
      wire('d1:BIN1', 'board:PB1'),
      wire('d1:BIN2', 'board:PB2'),
      wire('d1:PWMB', 'board:PB3')
    ]
  };
}

test('disconnected actuator power produces no response samples', () => {
  const circuit = poweredDriver();
  circuit.wires = circuit.wires.filter(item => item.a !== 'd1:VM' && item.b !== 'd1:VM');
  const result = evaluate({
    ...circuit,
    events: [
      { timeMs: 0, pin: 'PA0', value: 1 },
      { timeMs: 0, pin: 'PA1', value: 1 },
      { timeMs: 0, pin: 'PA3', value: 1 }
    ],
    durationMs: 100
  });
  const driver = outputFor(result, 'd1');
  assert.equal(driver.status, 'unpowered');
  assert.deepEqual(driver.samples, []);
});

test('valid SG90 1 ms and 2 ms pulses map to 0 and 180 degrees', () => {
  const circuit = poweredServo();
  const result = evaluate({
    ...circuit,
    events: [
      { timeMs: 0, pin: 'PA0', value: 1 },
      { timeMs: 1, pin: 'PA0', value: 0 },
      { timeMs: 20, pin: 'PA0', value: 1 },
      { timeMs: 22, pin: 'PA0', value: 0 }
    ],
    durationMs: 40
  });
  const servo = outputFor(result, 's1');
  assert.equal(servo.status, 'active');
  assert.deepEqual(servo.samples.map(sample => sample.angleDeg), [0, 180]);
  assert.deepEqual(servo.samples.map(sample => sample.timeMs), [1, 22]);
});

test('small 2 ms timing overshoot is tolerated while a 3 ms pulse is rejected', () => {
  const result = evaluate({
    ...poweredServo(),
    events: [
      { timeMs: 0, pin: 'PA0', value: 1 }, { timeMs: 2.005, pin: 'PA0', value: 0 },
      { timeMs: 20, pin: 'PA0', value: 1 }, { timeMs: 23, pin: 'PA0', value: 0 }
    ],
    durationMs: 30
  });
  const servo = outputFor(result, 's1');
  assert.equal(servo.status, 'active-with-invalid-input');
  assert.deepEqual(servo.samples.map(sample => sample.angleDeg), [180, 180]);
});

test('TB6612 channel follows STBY, direction pins, and observed PWM', () => {
  const circuit = poweredDriver();
  const result = evaluate({
    ...circuit,
    events: [
      { timeMs: 0, pin: 'PA0', value: 1 },
      { timeMs: 0, pin: 'PA1', value: 1 },
      { timeMs: 0, pin: 'PA2', value: 0 },
      { timeMs: 0, pin: 'PA3', value: 1 },
      { timeMs: 10, pin: 'PA1', value: 0 },
      { timeMs: 10, pin: 'PA2', value: 1 }
    ],
    durationMs: 20
  });
  const driver = outputFor(result, 'd1');
  assert.equal(driver.status, 'active');
  const channelA = driver.samples.filter(sample => sample.directionA);
  assert.deepEqual(channelA.map(sample => sample.directionA), ['forward', 'reverse']);
  assert.deepEqual(channelA.map(sample => sample.dutyA), [1, 1]);
});

test('TB6612 aggregate samples retain the other connected channel state', () => {
  const circuit = poweredDriver();
  const result = evaluate({
    ...circuit,
    events: [
      { timeMs: 0, pin: 'PA0', value: 1 },
      { timeMs: 0, pin: 'PA1', value: 1 },
      { timeMs: 0, pin: 'PA2', value: 0 },
      { timeMs: 0, pin: 'PA3', value: 1 },
      { timeMs: 0, pin: 'PB0', value: 1 },
      { timeMs: 0, pin: 'PB1', value: 0 },
      { timeMs: 0, pin: 'PB2', value: 1 },
      { timeMs: 0, pin: 'PB3', value: 1 },
      { timeMs: 10, pin: 'PB1', value: 1 },
      { timeMs: 10, pin: 'PB2', value: 0 }
    ],
    durationMs: 20
  });
  const samples = outputFor(result, 'd1').samples;
  assert.equal(samples.at(-1).directionA, 'forward');
  assert.equal(samples.at(-1).directionB, 'forward');
});

test('powered actuator with no GPIO trace does not invent activity', () => {
  const servo = evaluate({ ...poweredServo(), events: [], durationMs: 100 });
  const output = outputFor(servo, 's1');
  assert.equal(output.status, 'no-input');
  assert.deepEqual(output.samples, []);
});

test('ESC reports normalized command and encoder motor reports bounded ideal estimate', () => {
  const parts = [
    { id: 'e1', type: 'esc' },
    { id: 'd1', type: 'driver' },
    { id: 'm1', type: 'motor', ppr: 20, maxRpm: 3000 }
  ];
  const wires = [
    wire('e1:BAT+', 'board:5V'), wire('e1:BAT-', 'board:GND'),
    wire('e1:GND', 'board:GND'), wire('e1:SIG', 'board:PC0'),
    wire('d1:VM', 'board:5V'), wire('d1:VCC', 'board:3V3'), wire('d1:GND', 'board:GND'),
    wire('d1:STBY', 'board:PA0'), wire('d1:AIN1', 'board:PA1'),
    wire('d1:AIN2', 'board:PA2'), wire('d1:PWMA', 'board:PA3'),
    wire('d1:A01', 'm1:M+'), wire('d1:A02', 'm1:M-'),
    wire('m1:VCC', 'board:5V'), wire('m1:GND', 'board:GND')
  ];
  const events = [
    { timeMs: 0, pin: 'PC0', value: 1 }, { timeMs: 1.5, pin: 'PC0', value: 0 },
    { timeMs: 0, pin: 'PA0', value: 1 }, { timeMs: 0, pin: 'PA1', value: 1 },
    { timeMs: 0, pin: 'PA2', value: 0 }, { timeMs: 0, pin: 'PA3', value: 1 },
    { timeMs: 20, pin: 'PA1', value: 0 }, { timeMs: 20, pin: 'PA2', value: 1 }
  ];
  const result = evaluate({ parts, wires, events, durationMs: 40 });
  const esc = outputFor(result, 'e1');
  assert.equal(esc.samples[0].duty, 0.5);
  const motor = outputFor(result, 'm1');
  assert.equal(motor.samples[0].rpm, 3000);
  assert.equal(motor.samples.at(-1).timeMs, 40);
  assert.equal(motor.samples.at(-1).encoderCount, 0);
  assert.ok(motor.limitations.some(text => /encoder.*not supported/i.test(text)));
  assert.equal(result.outputs.filter(item => item.type === 'motor').length, 1);
});

test('invalid servo pulse holds a previous valid angle', () => {
  const result = evaluate({
    ...poweredServo(),
    events: [
      { timeMs: 0, pin: 'PA0', value: 1 }, { timeMs: 1.5, pin: 'PA0', value: 0 },
      { timeMs: 20, pin: 'PA0', value: 1 }, { timeMs: 22.5, pin: 'PA0', value: 0 }
    ],
    durationMs: 30
  });
  const servo = outputFor(result, 's1');
  assert.equal(servo.status, 'active-with-invalid-input');
  assert.deepEqual(servo.samples.map(sample => sample.angleDeg), [90, 90]);
});
