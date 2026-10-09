'use strict';

/*
 * ALIENTEK 精英 STM32F103 V1 physical pin map.
 *
 * The P1/P2 values below are copied from the author's V1 manual (figure
 * 2.1.2.1).  The photo is viewed component-side with the board silk upright:
 * odd numbered holes are on the right, even numbered holes on the left, and
 * pin 1 is the bottom row.  Keeping this data separate from the SVG renderer
 * lets project validation and the actuator graph use exactly the same map.
 */
(function exposeBoardMap(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else if (root) root.EliteBoardMap = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createBoardMap() {
  const PHOTO = Object.freeze({
    width: 915,
    height: 922,
    x: 140,
    y: 65,
    displayWidth: 520,
    displayHeight: 524
  });
  const nativeToSvg = (x, y) => ({
    x: PHOTO.x + x * PHOTO.displayWidth / PHOTO.width,
    y: PHOTO.y + y * PHOTO.displayHeight / PHOTO.height
  });
  const rowY = row => 196 + (704 - 196) * row / 26;

  // Connector table order is pin 1..54.  The physical photo runs in the
  // reverse direction, so board row 0 uses table row 26 and row 26 uses row 0.
  const P1_ODD = [
    'PE0', 'PE2', 'PE4', 'PE6', 'PF0', 'PF2', 'PF4', 'PF6', 'PF8', 'PF10',
    'PC1', 'PC3', 'PA1', 'PA5', 'PA7', 'PC5', 'PB1', 'PF11', 'PF13', 'PF15',
    'PG1', 'PE8', 'PE10', 'PE12', 'PE14', 'PB10', 'GND'
  ];
  const P1_EVEN = [
    'PB9', 'PE1', 'PE3', 'PE5', 'PC13', 'PF1', 'PF3', 'PF5', 'PF7', 'PF9',
    'PC0', 'PC2', 'PA0', 'PA4', 'PA6', 'PC4', 'PB0', 'PB2', 'PF12', 'PF14',
    'PG0', 'PE7', 'PE9', 'PE11', 'PE13', 'PE15', 'PB11'
  ];
  const P2_ODD = [
    'PB8', 'PB6', 'PB4', 'PG15', 'PG13', 'PG11', 'PG9', 'PD6', 'PD4', 'PD2',
    'PD0', 'PC11', 'PA15', 'PA13', 'PA11', 'PC9', 'PC7', 'PG8', 'PG6', 'PG4',
    'PG2', 'PD14', 'PD12', 'PD10', 'PD8', 'PB14', 'PB12'
  ];
  const P2_EVEN = [
    'PB7', 'PB5', 'PB3', 'PG14', 'PG12', 'PG10', 'PD7', 'PD5', 'PD3', 'PD1',
    'PC12', 'PC10', 'PA14', 'PA12', 'PA8', 'PC8', 'PC6', 'PG7', 'PG5', 'PG3',
    'PD15', 'PD13', 'PD11', 'PD9', 'PB15', 'PB13', 'GND'
  ];

  const mainHoles = [];
  const addHole = (header, pinNumber, signal, nativeX, row, kind = 'gpio') => {
    const nativeY = rowY(row);
    const id = kind === 'gpio' ? `board:${signal}` : `board:${signal}:${header}-${pinNumber}`;
    mainHoles.push(Object.freeze({
      id,
      canonical: kind === 'gpio' ? id : `board:${signal}`,
      header,
      pinNumber,
      signal,
      kind,
      nativeX,
      nativeY,
      ...nativeToSvg(nativeX, nativeY),
      address: `${header}-${pinNumber} · ${signal}`
    }));
  };
  for (let row = 0; row < 27; row += 1) {
    const oddPin = 53 - row * 2;
    const evenPin = oddPin + 1;
    const oddIndex = (oddPin - 1) / 2;
    const evenIndex = (evenPin - 2) / 2;
    for (const [header, odd, even, oddX, evenX] of [
      ['P1', P1_ODD, P1_EVEN, 780, 760],
      ['P2', P2_ODD, P2_EVEN, 256, 238]
    ]) {
      const oddSignal = odd[oddIndex];
      const evenSignal = even[evenIndex];
      addHole(header, oddPin, oddSignal, oddX, row, oddSignal === 'GND' ? 'power' : 'gpio');
      addHole(header, evenPin, evenSignal, evenX, row, evenSignal === 'GND' ? 'power' : 'gpio');
    }
  }

  // The four remaining GPIOs are on the small selector headers.  The yellow
  // jumpers partly cover these holes in the source photo; coordinates identify
  // the MCU-side holes and intentionally do not label CH340/RS485 aliases.
  const auxiliary = [
    { id: 'board:PA10', canonical: 'board:PA10', header: 'P3', pinNumber: 1, signal: 'PA10', nativeX: 126, nativeY: 458 },
    { id: 'board:PA9', canonical: 'board:PA9', header: 'P3', pinNumber: 3, signal: 'PA9', nativeX: 126, nativeY: 480 },
    { id: 'board:PA2', canonical: 'board:PA2', header: 'P5', pinNumber: 1, signal: 'PA2', nativeX: 790, nativeY: 15 },
    { id: 'board:PA3', canonical: 'board:PA3', header: 'P5', pinNumber: 2, signal: 'PA3', nativeX: 790, nativeY: 42 }
  ].map(hole => Object.freeze({
    ...hole,
    kind: 'gpio',
    ...nativeToSvg(hole.nativeX, hole.nativeY),
    address: `${hole.header}-${hole.pinNumber} · ${hole.signal}`
  }));
  // VOUT2 is the 5 V 3x2 header and VOUT1 is the 3.3 V 3x2 header.  In the
  // upright photo each top row is GND and each bottom row is its rail.
  // The first pad of each rail owns the legacy endpoint used by saved projects;
  // every other physical pad is an alias that canonicalizes to that rail.
  const powerPads = [];
  const addPowerHeader = (header, rail, label, topY, bottomY) => {
    [852, 872, 892].forEach((nativeX, index) => {
      const suffix = index + 1;
      const ground = {
        id: header === 'VOUT2' && index === 0 ? 'board:GND' : `board:GND:${header}-${suffix}`,
        canonical: 'board:GND',
        header,
        pinNumber: suffix,
        signal: 'GND',
        kind: 'power',
        nativeX,
        nativeY: topY,
        ...nativeToSvg(nativeX, topY),
        address: `${header}-${suffix} · GND`
      };
      const power = {
        id: header === 'VOUT2' && index === 0 && rail === '5V' ? 'board:5V' :
          header === 'VOUT1' && index === 0 && rail === '3V3' ? 'board:3V3' :
          `board:${rail}:${header}-${suffix}`,
        canonical: `board:${rail}`,
        header,
        pinNumber: suffix,
        signal: rail,
        kind: 'power',
        nativeX,
        nativeY: bottomY,
        ...nativeToSvg(nativeX, bottomY),
        address: `${header}-${suffix} · ${label}`
      };
      powerPads.push(Object.freeze(ground), Object.freeze(power));
    });
  };
  addPowerHeader('VOUT2', '5V', '5V', 252, 275);
  addPowerHeader('VOUT1', '3V3', '3V3', 306, 329);
  const compatibility = [
    Object.freeze({ id: 'board:PC14', signal: 'PC14', address: '兼容端点 · PC14 · RTC 晶振保留', x: 92, y: 625 }),
    Object.freeze({ id: 'board:PC15', signal: 'PC15', address: '兼容端点 · PC15 · RTC 晶振保留', x: 92, y: 658 })
  ];

  const GPIO_IDS = new Set();
  mainHoles.filter(hole => hole.kind === 'gpio').forEach(hole => GPIO_IDS.add(hole.id));
  auxiliary.forEach(hole => GPIO_IDS.add(hole.id));
  const POWER_ALIASES = new Map();
  powerPads.forEach(pad => POWER_ALIASES.set(pad.id, pad.canonical));
  mainHoles.filter(hole => hole.kind === 'power').forEach(hole => POWER_ALIASES.set(hole.id, hole.canonical));
  const SUPPORTED_ENDPOINTS = new Set([
    ...GPIO_IDS,
    'board:GND', 'board:3V3', 'board:5V',
    ...POWER_ALIASES.keys(),
    ...compatibility.map(item => item.id)
  ]);
  const GPIO_RE = /^board:P(?:[ABDEFG](?:0|[1-9]|1[0-5])|C(?:0|[1-9]|1[0-3]))$/;

  function normalizeEndpoint(value) {
    return typeof value === 'string' ? POWER_ALIASES.get(value) || value : value;
  }

  function isSupportedGpio(value) {
    return typeof value === 'string' && GPIO_IDS.has(value);
  }

  function normalizeGpioEvent(value) {
    if (typeof value !== 'string') return null;
    const raw = value.trim();
    const withPrefix = raw.startsWith('board:') ? raw : `board:${raw}`;
    const normalized = withPrefix.replace(/^board:P?([A-G])([0-9]|1[0-5])$/, 'board:P$1$2');
    return isSupportedGpio(normalized) ? normalized : null;
  }

  function isCompatibility(value) {
    return compatibility.some(item => item.id === value);
  }

  const endpointIds = Object.freeze([...SUPPORTED_ENDPOINTS]);
  const gpioIds = Object.freeze([...GPIO_IDS]);
  const physicalHoles = Object.freeze([...mainHoles, ...auxiliary, ...powerPads]);
  return Object.freeze({
    PHOTO,
    P1_ODD: Object.freeze(P1_ODD),
    P1_EVEN: Object.freeze(P1_EVEN),
    P2_ODD: Object.freeze(P2_ODD),
    P2_EVEN: Object.freeze(P2_EVEN),
    holes: physicalHoles,
    powerPads: Object.freeze(powerPads),
    auxiliary: Object.freeze(auxiliary),
    compatibility,
    gpioIds,
    endpointIds,
    normalizeEndpoint,
    normalizeGpioEvent,
    isSupportedGpio,
    isCompatibility,
    GPIO_RE
  });
});
