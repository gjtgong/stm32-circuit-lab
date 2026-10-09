# PE.JADO F103ZE CAD True 3D coverage

The board view now consumes the acquired PE.JADO F103ZE STM32F103ZET6
minimum-system-board source. `static/open-board-data.js` is generated locally by `python3 tools/fetch_open_board.py` and excluded from public distribution pending board reuse clarification; `static/open-board-map.js` adapts its source pads and named nets to
the existing `board:*` wiring API while retaining legacy project endpoint
aliases. The source board is 56.098 × 53.500 mm, uses the actual H1–H9 header
pads and U2 LQFP-144 footprint, and is rendered in the source coordinate frame.
The original source is attributed to PE.JADO at
[oshwhub.com/PE.JADO/stm32f103zet6](https://oshwhub.com/PE.JADO/stm32f103zet6),
labelled GPL-3.0-only in the acquisition record, with provenance in
`references/OPEN-BOARD-SOURCE.md`.

`static/board3d.js` renders the source outline, every converted pad, named
copper track, via, copper fill and source silk graphic. Copper can be shown as
top, bottom or both layers. Clicking a CAD pad or track highlights the same
source net and reports the net in the inspector. A highlighted net represents
source connectivity for engineering inspection; traces crossing on different
layers do not imply a short circuit, and the renderer does not claim current,
clearance, ERC/DRC or full electrical simulation. Package bodies are
approximate only where the source omits mechanical dimensions; placement,
pad coordinates, silk and route data remain source-derived.

The existing editor, imported ELF/C/H firmware flow, saved projects, external
module library and user wiring remain available. External modules continue to
respond through the existing bounded ARM GPIO/actuator models. `LED1` on the
CAD board is a 3V3 power indicator; PB5/PE5 trace-driven LEDs are external
modules and are not invented as onboard parts. The source-derived board does
not inherit the rejected Elite V1 photo or guessed component placement.

Three.js `0.160.0` and `OrbitControls` remain locally vendored from the
official npm package under MIT terms; the notice is in
`static/vendor/THREE-LICENSE`. WebGL failure is reported in place and does not
fall back to a board photograph.

## Verification

```bash
node --check static/open-board-map.js
node --check static/board3d.js
node --check static/app.js
node --test tests/open-board-mapping.test.cjs
```

The browser acceptance pass is owned by the lead agent. No browser profile or
localStorage state is modified by this renderer work.
