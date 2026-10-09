'use strict';

/*
 * Bounded actuator response models for the circuit-lab canvas.
 *
 * The module deliberately consumes only the circuit graph and the GPIO trace
 * produced by the firmware runner.  It does not run firmware, create GPIO
 * events, or feed an estimated encoder value back into that runner.
 *
 * Browser use:
 *   window.ActuatorModels.evaluate({ parts, wires, events, durationMs })
 *
 * Node use:
 *   const { evaluate } = require('./static/actuators.js');
 *
 * The models are intentionally bounded and open-loop:
 * - a TB6612 channel is a digital truth-table plus an observed PWM duty;
 * - an ESC reports a normalized 1--2 ms command only;
 * - an SG90 reports the angle represented by a valid 1--2 ms pulse;
 * - an encoder motor reports an ideal signed target rpm and an estimated
 *   encoder count when it is attached to a modeled TB6612 channel.
 *
 * No result below is a physical speed measurement.  In particular, estimated
 * encoder counts are never emitted as MCU input trace events.
 */

(function exposeActuatorModels(root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ActuatorModels = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createApi(root) {
  const DEFAULT_DURATION_MS = 2000;
  const MAX_DURATION_MS = 120000;
  const DEFAULT_MAX_RPM = 3000;
  const DEFAULT_PPR = 20;
  const MIN_SERVO_PULSE_MS = 1;
  const MAX_SERVO_PULSE_MS = 2;
  const MIN_COMMAND_PULSE_MS = 1;
  const MAX_COMMAND_PULSE_MS = 2;
  // The firmware runner's 1 ms tick can make a nominal 2 ms pulse arrive a
  // few microseconds late.  Keep the tolerance small enough that a 3 ms
  // pulse remains clearly invalid.
  const PULSE_TIMING_TOLERANCE_MS = 0.02;

  const ACTUATOR_TYPES = new Set([
    'driver', 'tb6612', 'tb6612-driver', 'motor-driver',
    'esc',
    'motor', 'encoder-motor',
    'servo', 'sg90'
  ]);

  const DRIVER_TYPES = new Set(['driver', 'tb6612', 'tb6612-driver', 'motor-driver']);
  const ESC_TYPES = new Set(['esc']);
  const MOTOR_TYPES = new Set(['motor', 'encoder-motor']);
  const SERVO_TYPES = new Set(['servo', 'sg90']);
  const BOARD_MAP = root && root.EliteBoardMap ||
    (typeof require === 'function' ? require('./board-map.js') : null);
  const BOARD_GPIO_RE = BOARD_MAP?.GPIO_RE || /^board:P([A-G])(?:([0-9])|(1[0-5]))$/;
  const normalizeEndpoint = value => BOARD_MAP ? BOARD_MAP.normalizeEndpoint(value) : value;

  const LIMITATIONS = {
    driver:
      'TB6612 is modeled as a digital truth table with duty decoded from observed GPIO transitions; current, voltage drop, thermal behavior, and H-bridge dynamics are not modeled.',
    ideal5V:
      'For this bounded model, board:5V is treated as an ideal actuator supply.',
    esc:
      'ESC output is an open-loop normalized 1–2 ms command only; commutation, back-EMF, current, load, and real-speed physics are not modeled.',
    servo:
      'SG90 output is the commanded pulse angle only; torque, load, travel dynamics, and position feedback are not modeled.',
    encoder:
      'Encoder ENC_A/ENC_B pulse return to the MCU is not supported; encoderCount is an ideal estimate and is never injected into the GPIO trace.'
  };

  function finiteNumber(value) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function asPositiveNumber(value, fallback) {
    return finiteNumber(value) && value > 0 ? value : fallback;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function uniqueStrings(values) {
    return [...new Set(values.filter(value => typeof value === 'string'))];
  }

  function normalizePartType(type) {
    return typeof type === 'string' ? type.toLowerCase() : '';
  }

  function normalizeEventPin(pin) {
    if (BOARD_MAP) return BOARD_MAP.normalizeGpioEvent(pin);
    if (typeof pin !== 'string') return null;
    const value = pin.trim();
    if (/^board:P[A-G](?:[0-9]|1[0-5])$/.test(value)) return value;
    if (/^P[A-G](?:[0-9]|1[0-5])$/.test(value)) return `board:${value}`;
    if (/^board:PA(?:[0-9]|1[0-5])$/.test(value) ||
        /^board:PB(?:[0-9]|1[0-5])$/.test(value) ||
        /^board:PC(?:[0-9]|1[0-5])$/.test(value) ||
        /^board:PD(?:[0-9]|1[0-5])$/.test(value) ||
        /^board:PE(?:[0-9]|1[0-5])$/.test(value) ||
        /^board:PF(?:[0-9]|1[0-5])$/.test(value) ||
        /^board:PG(?:[0-9]|1[0-5])$/.test(value)) return value;
    if (/^P[A-G](?:[0-9]|1[0-5])$/.test(value)) return `board:${value}`;
    if (/^[A-G](?:[0-9]|1[0-5])$/.test(value)) return `board:P${value}`;
    return null;
  }

  function digitalValue(value) {
    if (value === true || value === 1) return 1;
    if (value === false || value === 0) return 0;
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      if (['1', 'true', 'high', 'on'].includes(normalized)) return 1;
      if (['0', 'false', 'low', 'off'].includes(normalized)) return 0;
    }
    return null;
  }

  function makeGraph(parts, wires, warnings) {
    const adjacency = new Map();
    const ensure = node => {
      if (!adjacency.has(node)) adjacency.set(node, new Set());
      return adjacency.get(node);
    };

    for (const wire of wires) {
      if (!wire || typeof wire.a !== 'string' || typeof wire.b !== 'string') {
        warnings.push('Ignored a wire without string endpoints.');
        continue;
      }
      const a = normalizeEndpoint(wire.a);
      const b = normalizeEndpoint(wire.b);
      ensure(a).add(b);
      ensure(b).add(a);
    }
    for (const part of parts) {
      if (part && typeof part.id === 'string') {
        // A node with no wire is intentionally kept isolated.  This is useful
        // for distinguishing an unconnected actuator from an unpowered one.
        ensure(part.id);
      }
    }

    const cache = new Map();
    function net(node) {
      if (cache.has(node)) return cache.get(node);
      const result = new Set([node]);
      const queue = [node];
      while (queue.length) {
        const current = queue.pop();
        for (const next of adjacency.get(current) || []) {
          if (!result.has(next)) {
            result.add(next);
            queue.push(next);
          }
        }
      }
      cache.set(node, result);
      return result;
    }

    return { net };
  }

  function isBoardGpio(node) {
    return BOARD_MAP ? BOARD_MAP.isSupportedGpio(node) : typeof node === 'string' && BOARD_GPIO_RE.test(node);
  }

  function netSignal(graph, node) {
    const nodes = graph.net(node);
    const gpioPins = [...nodes].filter(isBoardGpio).sort();
    let fixedValue = null;
    if (nodes.has('board:3V3') || nodes.has('board:5V')) fixedValue = 1;
    else if (nodes.has('board:GND')) fixedValue = 0;
    return {
      connected: gpioPins.length > 0 || fixedValue !== null,
      gpioPins,
      fixedValue
    };
  }

  function hasRail(graph, node, rail) {
    return graph.net(node).has(rail);
  }

  function hasAnyRail(graph, node, rails) {
    const nodes = graph.net(node);
    return rails.some(rail => nodes.has(rail));
  }

  function hasGround(graph, node) {
    return hasRail(graph, node, 'board:GND');
  }

  function signalChanges(signal, eventByPin) {
    if (!signal || !signal.gpioPins.length) return [];
    const changes = [];
    for (const pin of signal.gpioPins) {
      for (const event of eventByPin.get(pin) || []) changes.push(event);
    }
    changes.sort((a, b) => a.timeMs - b.timeMs || a.order - b.order);
    return changes;
  }

  function signalDefault(signal) {
    return signal && signal.fixedValue !== null ? signal.fixedValue : 0;
  }

  function allSignalTimes(signals) {
    const times = new Set();
    for (const signal of signals) {
      for (const change of signal.changes || []) times.add(change.timeMs);
    }
    return [...times].sort((a, b) => a - b);
  }

  function stateAt(signal, timeMs) {
    let value = signalDefault(signal);
    for (const change of signal.changes || []) {
      if (change.timeMs > timeMs) break;
      value = change.value;
    }
    return value;
  }

  function pulsePairs(signal) {
    const pulses = [];
    let value = signalDefault(signal);
    let risingAt = value ? 0 : null;
    for (const change of signal.changes || []) {
      if (change.value === value) continue;
      if (!value && change.value) risingAt = change.timeMs;
      else if (value && !change.value && risingAt !== null) {
        pulses.push({ startMs: risingAt, endMs: change.timeMs, widthMs: change.timeMs - risingAt });
        risingAt = null;
      }
      value = change.value;
    }
    return pulses;
  }

  function pulsePeriodWarnings(signal, pulses) {
    const warnings = [];
    for (let index = 1; index < pulses.length; index += 1) {
      const period = pulses[index].startMs - pulses[index - 1].startMs;
      // The nominal SG90/RC command frame is about 20 ms.  A broad tolerance
      // keeps valid traces from being rejected while still exposing an
      // accidentally one-shot or extremely fast command stream.
      if (period < 10 || period > 40) {
        warnings.push(`Observed pulse period ${period} ms; expected approximately 20 ms.`);
      }
    }
    return warnings;
  }

  function validCommandPulse(widthMs) {
    return widthMs >= MIN_COMMAND_PULSE_MS &&
      widthMs <= MAX_COMMAND_PULSE_MS + PULSE_TIMING_TOLERANCE_MS;
  }

  function validateInput(input) {
    const source = input && typeof input === 'object' ? input : {};
    const warnings = [];
    const parts = Array.isArray(source.parts) ? source.parts.filter(Boolean) : [];
    const wires = Array.isArray(source.wires) ? source.wires.filter(Boolean) : [];
    const rawEvents = Array.isArray(source.events) ? source.events : [];
    let durationMs = finiteNumber(source.durationMs) ? source.durationMs : DEFAULT_DURATION_MS;
    if (durationMs < 0) {
      warnings.push('durationMs was negative; using 0 ms.');
      durationMs = 0;
    }
    if (durationMs > MAX_DURATION_MS) {
      warnings.push(`durationMs was capped at ${MAX_DURATION_MS} ms.`);
      durationMs = MAX_DURATION_MS;
    }

    const eventByPin = new Map();
    const events = [];
    rawEvents.forEach((raw, order) => {
      if (!raw || !finiteNumber(raw.timeMs)) {
        warnings.push('Ignored a GPIO event without a finite timeMs.');
        return;
      }
      const pin = normalizeEventPin(raw.pin);
      const value = digitalValue(raw.value);
      if (!pin || value === null) {
        warnings.push('Ignored a GPIO event with an invalid pin or digital value.');
        return;
      }
      if (raw.timeMs < 0 || raw.timeMs > durationMs) return;
      const event = { timeMs: raw.timeMs, pin, value, order };
      events.push(event);
      if (!eventByPin.has(pin)) eventByPin.set(pin, []);
      eventByPin.get(pin).push(event);
    });
    events.sort((a, b) => a.timeMs - b.timeMs || a.order - b.order);
    for (const values of eventByPin.values()) values.sort((a, b) => a.timeMs - b.timeMs || a.order - b.order);

    const ids = new Set();
    const validParts = [];
    for (const part of parts) {
      if (typeof part.id !== 'string' || !part.id) {
        warnings.push('Ignored a part without a string id.');
        continue;
      }
      if (ids.has(part.id)) {
        warnings.push(`Ignored duplicate part id ${part.id}.`);
        continue;
      }
      ids.add(part.id);
      validParts.push(part);
      if (typeof part.type !== 'string') warnings.push(`Part ${part.id} has no type.`);
    }

    return { source, warnings, parts: validParts, wires, events, eventByPin, durationMs };
  }

  function baseOutput(part, type, limitations) {
    return {
      partId: part.id,
      type,
      samples: [],
      status: 'unconnected',
      limitations: uniqueStrings(limitations)
    };
  }

  function finishStatus(output, options) {
    const { powered, connected, samples, invalid, hadValid } = options;
    if (!powered) output.status = 'unpowered';
    else if (!connected) output.status = 'unconnected';
    else if (!samples.length && invalid && !hadValid) output.status = 'invalid-input';
    else if (!samples.length) output.status = 'no-input';
    else if (invalid) output.status = 'active-with-invalid-input';
    else output.status = 'active';
    return output;
  }

  function evaluateServo(part, graph, eventByPin, durationMs) {
    const output = baseOutput(part, part.type, [LIMITATIONS.servo, LIMITATIONS.ideal5V]);
    const powered = hasRail(graph, `${part.id}:V+`, 'board:5V') && hasGround(graph, `${part.id}:GND`);
    const signal = netSignal(graph, `${part.id}:PWM`);
    signal.changes = signalChanges(signal, eventByPin);
    const pulses = powered && signal.connected ? pulsePairs(signal) : [];
    const periodWarnings = pulsePeriodWarnings(signal, pulses);
    let angle = null;
    let invalid = false;
    for (const pulse of pulses) {
      if (!validCommandPulse(pulse.widthMs)) {
        invalid = true;
        if (angle !== null) output.samples.push({ timeMs: pulse.endMs, angleDeg: clamp(angle, 0, 180) });
        continue;
      }
      angle = (pulse.widthMs - MIN_SERVO_PULSE_MS) /
        (MAX_SERVO_PULSE_MS - MIN_SERVO_PULSE_MS) * 180;
      output.samples.push({ timeMs: pulse.endMs, angleDeg: clamp(angle, 0, 180) });
    }
    // Invalid pulses hold the last valid command.  A first invalid pulse has
    // no prior position, so it intentionally produces no invented sample.
    output.samples.sort((a, b) => a.timeMs - b.timeMs);
    for (const warning of periodWarnings) output.limitations.push(warning);
    if (invalid) output.limitations.push('Out-of-range pulses are rejected and hold the last valid angle.');
    return finishStatus(output, {
      powered,
      connected: signal.connected,
      samples: output.samples,
      invalid,
      hadValid: output.samples.length > 0
    });
  }

  function evaluateEsc(part, graph, eventByPin) {
    const output = baseOutput(part, part.type, [LIMITATIONS.esc, LIMITATIONS.ideal5V]);
    const powered = hasRail(graph, `${part.id}:BAT+`, 'board:5V') &&
      hasGround(graph, `${part.id}:BAT-`) && hasGround(graph, `${part.id}:GND`);
    const signal = netSignal(graph, `${part.id}:SIG`);
    signal.changes = signalChanges(signal, eventByPin);
    const pulses = powered && signal.connected ? pulsePairs(signal) : [];
    const periodWarnings = pulsePeriodWarnings(signal, pulses);
    let duty = null;
    let invalid = false;
    for (const pulse of pulses) {
      if (!validCommandPulse(pulse.widthMs)) {
        invalid = true;
        if (duty !== null) output.samples.push({ timeMs: pulse.endMs, duty });
        continue;
      }
      duty = clamp((pulse.widthMs - MIN_COMMAND_PULSE_MS) /
        (MAX_COMMAND_PULSE_MS - MIN_COMMAND_PULSE_MS), 0, 1);
      output.samples.push({ timeMs: pulse.endMs, duty });
    }
    output.samples.sort((a, b) => a.timeMs - b.timeMs);
    for (const warning of periodWarnings) output.limitations.push(warning);
    if (invalid) output.limitations.push('Out-of-range ESC pulses are rejected and hold the last valid duty.');
    return finishStatus(output, {
      powered,
      connected: signal.connected,
      samples: output.samples,
      invalid,
      hadValid: output.samples.length > 0
    });
  }

  function pwmDutyAt(signal, timeMs) {
    const initial = signalDefault(signal);
    let value = initial;
    let risingAt = initial ? 0 : null;
    let previousFall = initial ? 0 : 0;
    let latestDuty = initial ? 1 : 0;
    for (const change of signal.changes || []) {
      if (change.timeMs > timeMs) break;
      if (change.value === value) continue;
      if (!value && change.value) {
        risingAt = change.timeMs;
      } else if (value && !change.value && risingAt !== null) {
        const width = change.timeMs - risingAt;
        const low = Math.max(0, risingAt - previousFall);
        const period = width + low;
        latestDuty = period > 0 ? clamp(width / period, 0, 1) : 1;
        previousFall = change.timeMs;
        risingAt = null;
      }
      value = change.value;
    }
    if (value && risingAt !== null && latestDuty === 0) latestDuty = 1;
    // A low PWM gate means the modeled H-bridge output is low at this sample;
    // the high-pulse ratio is retained by the next high sample.
    return value ? clamp(latestDuty, 0, 1) : 0;
  }

  function truthTable(stby, in1, in2, pwm, duty) {
    if (!stby) return { direction: 'standby', duty: 0, signed: 0 };
    if (!pwm) return { direction: 'pwm-low', duty: 0, signed: 0 };
    if (!in1 && !in2) return { direction: 'stop', duty, signed: 0 };
    if (in1 && !in2) return { direction: 'forward', duty, signed: duty };
    if (!in1 && in2) return { direction: 'reverse', duty, signed: -duty };
    return { direction: 'brake', duty, signed: 0 };
  }

  function makeDriverChannel(part, channel, graph, eventByPin) {
    const prefix = channel === 'A' ? 'A' : 'B';
    const signals = {
      stby: netSignal(graph, `${part.id}:STBY`),
      in1: netSignal(graph, `${part.id}:${prefix}IN1`),
      in2: netSignal(graph, `${part.id}:${prefix}IN2`),
      pwm: netSignal(graph, `${part.id}:PWM${prefix}`)
    };
    for (const signal of Object.values(signals)) {
      signal.changes = signalChanges(signal, eventByPin);
    }
    const connected = Object.values(signals).every(signal => signal.connected);
    if (!connected) return { channel, signals, connected, samples: [], times: [] };
    const times = allSignalTimes(Object.values(signals));
    const samples = [];
    for (const timeMs of times) {
      const stby = stateAt(signals.stby, timeMs);
      const in1 = stateAt(signals.in1, timeMs);
      const in2 = stateAt(signals.in2, timeMs);
      const pwm = stateAt(signals.pwm, timeMs);
      const duty = pwmDutyAt(signals.pwm, timeMs);
      const mode = truthTable(stby, in1, in2, pwm, duty);
      samples.push({ timeMs, channel, ...mode, _signedDuty: mode.signed });
    }
    return { channel, signals, connected, samples, times };
  }

  function publicDriverSample(sample, channel) {
    const suffix = channel;
    const result = {
      timeMs: sample.timeMs,
      duty: sample.duty,
      direction: sample.direction
    };
    // The generic fields make a single-channel TB6612 convenient for the
    // inspector.  Explicit fields retain both channels when both are wired.
    result[`duty${suffix}`] = sample.duty;
    result[`direction${suffix}`] = sample.direction;
    return result;
  }

  function evaluateDriver(part, graph, eventByPin) {
    const output = baseOutput(part, part.type, [LIMITATIONS.driver, LIMITATIONS.ideal5V]);
    const powered = hasRail(graph, `${part.id}:VM`, 'board:5V') &&
      hasAnyRail(graph, `${part.id}:VCC`, ['board:3V3', 'board:5V']) &&
      hasGround(graph, `${part.id}:GND`);
    const channelA = makeDriverChannel(part, 'A', graph, eventByPin);
    const channelB = makeDriverChannel(part, 'B', graph, eventByPin);
    const channels = [channelA, channelB];
    const connectedChannels = channels.filter(channel => channel.connected);
    const connected = connectedChannels.length > 0;
    const byTime = new Set();
    for (const channel of connectedChannels) {
      for (const sample of channel.samples) byTime.add(sample.timeMs);
    }
    const sortedTimes = [...byTime].sort((a, b) => a - b);
    for (const timeMs of sortedTimes) {
      const sample = { timeMs };
      const latest = new Map();
      for (const channel of connectedChannels) {
        for (const candidate of channel.samples) {
          if (candidate.timeMs > timeMs) break;
          latest.set(channel.channel, candidate);
        }
        const channelSample = latest.get(channel.channel);
        if (channelSample) Object.assign(sample, publicDriverSample(channelSample, channel.channel));
      }
      // Generic fields refer to channel A when it is wired; otherwise they
      // refer to channel B.  Explicit A/B fields above retain each channel's
      // last observed state across the other channel's later events.
      const genericChannel = latest.get('A') || latest.get('B');
      if (genericChannel) {
        sample.duty = genericChannel.duty;
        sample.direction = genericChannel.direction;
      }
      output.samples.push(sample);
    }
    // Power and signal presence gate the response.  GPIO transitions alone
    // cannot make an unpowered H-bridge active.
    if (!powered || !connected) output.samples = [];
    // Keep the private channel traces available to motor evaluation without
    // exposing extra top-level API fields.
    output._channels = channels;
    return finishStatus(output, {
      powered,
      connected,
      samples: output.samples,
      invalid: false,
      hadValid: output.samples.length > 0
    });
  }

  function connectedMotorChannel(motor, drivers, graph) {
    const motorPlus = `${motor.id}:M+`;
    const motorMinus = `${motor.id}:M-`;
    const plusNet = graph.net(motorPlus);
    const minusNet = graph.net(motorMinus);
    for (const driver of drivers) {
      for (const channel of driver._channels || []) {
        const prefix = channel.channel;
        const out1 = `${driver.partId}:A01`;
        const out2 = `${driver.partId}:A02`;
        const pin1 = prefix === 'A' ? out1 : `${driver.partId}:B01`;
        const pin2 = prefix === 'A' ? out2 : `${driver.partId}:B02`;
        const net1 = graph.net(pin1);
        const net2 = graph.net(pin2);
        if (plusNet.has(pin1) && minusNet.has(pin2)) {
          return { driver, channel, polarity: 1 };
        }
        if (plusNet.has(pin2) && minusNet.has(pin1)) {
          return { driver, channel, polarity: -1 };
        }
        // The variables above intentionally cause net() to cache each output;
        // this branch keeps the relation explicit for readers of the truth
        // table and avoids accidentally matching one terminal only.
        void net1;
        void net2;
      }
    }
    return null;
  }

  function evaluateMotor(part, graph, drivers, options) {
    const output = baseOutput(part, part.type, [LIMITATIONS.encoder]);
    const attachment = connectedMotorChannel(part, drivers, graph);
    const motorPowered = hasAnyRail(graph, `${part.id}:VCC`, ['board:3V3', 'board:5V']) &&
      hasGround(graph, `${part.id}:GND`);
    const driverPowered = Boolean(attachment && attachment.driver.status !== 'unpowered');
    const powered = motorPowered && driverPowered;
    const connected = Boolean(attachment);
    if (!powered || !connected) {
      return finishStatus(output, {
        powered,
        connected,
        samples: output.samples,
        invalid: false,
        hadValid: false
      });
    }

    const maxRpm = asPositiveNumber(
      part.maxRpm,
      asPositiveNumber(attachment.driver._part && attachment.driver._part.maxRpm,
        asPositiveNumber(options.maxRpm, DEFAULT_MAX_RPM))
    );
    const ppr = asPositiveNumber(
      part.ppr,
      asPositiveNumber(part.encoderPpr, asPositiveNumber(options.ppr, DEFAULT_PPR))
    );
    let count = 0;
    let previousTime = null;
    let previousRpm = 0;
    let previousDuty = 0;
    let previousDirection = 'pwm-low';
    for (const source of attachment.channel.samples) {
      if (previousTime !== null) {
        count += previousRpm / 60 * ppr * (source.timeMs - previousTime) / 1000;
      }
      const signed = source._signedDuty * maxRpm * attachment.polarity;
      const rpm = Math.round(signed * 1000000) / 1000000;
      let direction = source.direction;
      if (attachment.polarity < 0) {
        if (direction === 'forward') direction = 'reverse';
        else if (direction === 'reverse') direction = 'forward';
      }
      const sample = {
        timeMs: source.timeMs,
        duty: source.duty,
        rpm,
        direction,
        encoderCount: Math.round(count)
      };
      output.samples.push(sample);
      previousTime = source.timeMs;
      previousRpm = rpm;
      previousDuty = source.duty;
      previousDirection = direction;
    }
    // Once the firmware has produced at least one real control event, carry
    // the last observed command to durationMs for the ideal count estimate.
    // This is a model output, never a synthesized MCU input trace.
    const durationMs = finiteNumber(options.durationMs) ? options.durationMs : DEFAULT_DURATION_MS;
    if (previousTime !== null && previousTime < durationMs) {
      count += previousRpm / 60 * ppr * (durationMs - previousTime) / 1000;
      output.samples.push({
        timeMs: durationMs,
        duty: previousDuty,
        rpm: previousRpm,
        direction: previousDirection,
        encoderCount: Math.round(count)
      });
    }
    output.limitations.push(`Ideal target rpm uses maxRpm=${maxRpm} and encoder ppr=${ppr}; it is not a measured speed.`);
    return finishStatus(output, {
      powered,
      connected,
      samples: output.samples,
      invalid: false,
      hadValid: output.samples.length > 0
    });
  }

  function evaluate(input) {
    const validated = validateInput(input);
    const { warnings, parts, wires, eventByPin, durationMs } = validated;
    const graph = makeGraph(parts, wires, warnings);
    const outputs = [];
    const driverOutputs = [];

    for (const part of parts) {
      const type = normalizePartType(part.type);
      if (!ACTUATOR_TYPES.has(type)) continue;
      if (DRIVER_TYPES.has(type)) {
        const output = evaluateDriver(part, graph, eventByPin);
        output._part = part;
        driverOutputs.push(output);
        outputs.push(output);
      } else if (SERVO_TYPES.has(type)) {
        outputs.push(evaluateServo(part, graph, eventByPin, durationMs));
      } else if (ESC_TYPES.has(type)) {
        outputs.push(evaluateEsc(part, graph, eventByPin));
      }
    }
    for (const part of parts) {
      const type = normalizePartType(part.type);
      if (MOTOR_TYPES.has(type)) outputs.push(evaluateMotor(part, graph, driverOutputs, validated.source));
    }

    // Private bookkeeping is removed before returning so the public shape is
    // exactly outputs + warnings.  The motor evaluation above has already
    // consumed it.
    for (const output of outputs) {
      delete output._channels;
      delete output._part;
    }
    return { outputs, warnings: uniqueStrings(warnings) };
  }

  return {
    evaluate,
    constants: {
      DEFAULT_DURATION_MS,
      MAX_DURATION_MS,
      DEFAULT_MAX_RPM,
      DEFAULT_PPR
    }
  };
});
