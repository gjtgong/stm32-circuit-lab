'use strict';

/*
 * Pure trace helpers for the V1 physical LEDs.
 *
 * The runner reports ordinary GPIO edges (`PB5` / `PE5`, value 0 or 1).
 * The board LEDs sink current, so the low portion of an interval is the
 * illuminated portion.  Keeping this file free of DOM/Three.js code makes
 * the firmware-to-light contract testable without an animation mock.
 */
(function exposeSignals(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.OnboardSignals = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createSignals() {
  const CHANNELS = Object.freeze({
    PB5: Object.freeze({ pin: 'PB5', name: 'LED0 / DS0', color: '#e34a4a', activeLow: true }),
    PE5: Object.freeze({ pin: 'PE5', name: 'LED1 / DS1', color: '#67d38c', activeLow: true })
  });

  function normalizePin(pin) {
    if (typeof pin !== 'string') return '';
    const value = pin.trim().toUpperCase().replace(/^BOARD:/, '');
    return value.startsWith('P') ? value : `P${value}`;
  }

  function eventsFor(trace, pin) {
    const wanted = normalizePin(pin);
    return (Array.isArray(trace) ? trace : [])
      .filter(event => normalizePin(event?.pin) === wanted && Number.isFinite(Number(event?.timeMs)))
      .map(event => ({
        timeMs: Math.max(0, Number(event.timeMs)),
        value: event.value ? 1 : 0
      }))
      .sort((a, b) => a.timeMs - b.timeMs);
  }

  function durationOf(trace, durationMs) {
    if (Number.isFinite(Number(durationMs)) && Number(durationMs) > 0) return Number(durationMs);
    const times = (Array.isArray(trace) ? trace : [])
      .map(event => Number(event?.timeMs))
      .filter(Number.isFinite);
    return Math.max(1, ...times);
  }

  // Integrate the measured low interval over [startMs, endMs].  State before
  // the first captured edge follows the MCU reset-safe HIGH/off state.
  function lowDuration(trace, pin, startMs = 0, endMs = durationOf(trace)) {
    const start = Math.max(0, Number(startMs) || 0);
    const end = Math.max(start, Number(endMs) || start);
    if (end <= start) return 0;
    const events = eventsFor(trace, pin);
    let state = 1;
    for (const event of events) {
      if (event.timeMs > start) break;
      state = event.value;
    }
    let cursor = start;
    let low = 0;
    for (const event of events) {
      if (event.timeMs <= start) continue;
      if (event.timeMs >= end) break;
      if (state === 0) low += event.timeMs - cursor;
      cursor = event.timeMs;
      state = event.value;
    }
    if (state === 0) low += end - cursor;
    return Math.max(0, Math.min(end - start, low));
  }

  function lowDuty(trace, pin, durationMs) {
    const duration = durationOf(trace, durationMs);
    return lowDuration(trace, pin, 0, duration) / duration;
  }

  function valueAt(trace, pin, timeMs = 0) {
    let value = 1;
    const at = Math.max(0, Number(timeMs) || 0);
    for (const event of eventsFor(trace, pin)) {
      if (event.timeMs > at) break;
      value = event.value;
    }
    return value;
  }

  // A short rolling window keeps the dome responsive to real PWM duty while
  // never inventing a periodic waveform.  Constant HIGH stays dark and
  // constant LOW stays fully bright.
  function brightnessAt(trace, pin, timeMs = 0, durationMs, windowMs = 20) {
    const duration = durationOf(trace, durationMs);
    const at = Math.max(0, Math.min(duration, Number(timeMs) || 0));
    const half = Math.max(1, Number(windowMs) || 20) / 2;
    const start = Math.max(0, at - half);
    const end = Math.min(duration, at + half);
    if (end <= start) return valueAt(trace, pin, at) === 0 ? 1 : 0;
    return lowDuration(trace, pin, start, end) / (end - start);
  }

  function summarize(trace, durationMs) {
    const duration = durationOf(trace, durationMs);
    return Object.fromEntries(Object.keys(CHANNELS).map(pin => [pin, {
      ...CHANNELS[pin],
      durationMs: duration,
      lowDuty: lowDuty(trace, pin, duration),
      value: valueAt(trace, pin, duration)
    }]));
  }

  return Object.freeze({ CHANNELS, normalizePin, eventsFor, durationOf, lowDuration, lowDuty, valueAt, brightnessAt, summarize });
});
