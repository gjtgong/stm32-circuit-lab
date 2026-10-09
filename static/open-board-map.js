'use strict';

/*
 * Compatibility map for the source-derived PE.JADO board.  The converter
 * owns open-board-data.js; this file only turns its named header pads and
 * nets into the endpoint API consumed by the existing wiring editor.
 */
(function exposeOpenBoardMap(root) {
  const data = root && root.OpenBoardData;
  if (!data || !Array.isArray(data.pads)) return;

  const GPIO_RE = /^P[A-G](?:[0-9]|1[0-5])$/;
  const aliases = new Map();
  const padEndpoints = Object.create(null);
  const holes = [];
  const powerPads = [];
  const auxiliary = [];
  const gpioIds = new Set();
  const endpointIds = new Set();
  const headerRe = /^H[1-9]$/i;

  function cleanNet(value) {
    const net = String(value || '').trim();
    if (!net) return '';
    if (net === '+5V' || net === '5V' || net === 'VCC') return '5V';
    if (net === '3.3V' || net === '3V3' || net === 'VDD') return '3V3';
    if (net === 'GND' || net === 'AGND') return 'GND';
    return net;
  }

  function endpointForNet(net, padId) {
    const cleaned = cleanNet(net);
    if (!cleaned) return null;
    const canonical = `board:${cleaned}`;
    if (GPIO_RE.test(cleaned)) {
      gpioIds.add(canonical);
      endpointIds.add(canonical);
      return canonical;
    }
    if (['board:GND', 'board:3V3', 'board:5V'].includes(canonical)) {
      endpointIds.add(canonical);
      if (padId) {
        const alias = `${canonical}:${padId}`;
        aliases.set(alias, canonical);
        endpointIds.add(alias);
        return alias;
      }
      return canonical;
    }
    return null;
  }

  for (const pad of data.pads) {
    const ref = String(pad.ref || '').toUpperCase();
    const net = cleanNet(pad.net);
    const endpoint = endpointForNet(net, pad.id);
    if (endpoint) padEndpoints[pad.id] = endpoint;
    if (!headerRe.test(ref)) continue;
    const item = Object.freeze({
      id: endpoint || `board:pad:${pad.id}`,
      canonical: endpoint ? (aliases.get(endpoint) || endpoint) : `board:pad:${pad.id}`,
      padId: pad.id,
      header: ref,
      pinNumber: pad.number,
      signal: net,
      kind: GPIO_RE.test(net) ? 'gpio' : (['GND', '3V3', '5V'].includes(net) ? 'power' : 'auxiliary'),
      nativeX: pad.x,
      nativeY: pad.y,
      x: pad.x,
      y: pad.y,
      address: `${ref}-${pad.number || pad.id} · ${net || 'unassigned'}`
    });
    holes.push(item);
    if (item.kind === 'power') powerPads.push(item);
    if (ref === 'H9') auxiliary.push(item);
  }

  for (const pad of data.pads) {
    const net = cleanNet(pad.net);
    const endpoint = endpointForNet(net);
    if (endpoint) endpointIds.add(endpoint);
  }

  function normalizeEndpoint(value) {
    return aliases.get(value) || value;
  }

  function isSupportedGpio(value) {
    return gpioIds.has(normalizeEndpoint(value));
  }

  function normalizeGpioEvent(value) {
    if (typeof value !== 'string') return null;
    const raw = value.trim().replace(/^board:/, '');
    const candidate = `board:${raw}`;
    return isSupportedGpio(candidate) ? normalizeEndpoint(candidate) : null;
  }

  const api = Object.freeze({
    meta: data.meta,
    PHOTO: null,
    holes: Object.freeze(holes),
    powerPads: Object.freeze(powerPads),
    auxiliary: Object.freeze(auxiliary),
    compatibility: Object.freeze([]),
    gpioIds: Object.freeze([...gpioIds]),
    endpointIds: Object.freeze([...endpointIds]),
    padEndpoints: Object.freeze(padEndpoints),
    endpointForPad: padId => padEndpoints[padId] || null,
    normalizeEndpoint,
    normalizeGpioEvent,
    isSupportedGpio,
    isCompatibility: () => false
  });
  root.OpenBoardMap = api;
  root.EliteBoardMap = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);

