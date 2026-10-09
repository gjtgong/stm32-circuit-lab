# Open-source 3D implementation review

Checked 2026-10-09. All source links below are pinned to the reviewed commit where practical. No third-party repository code was executed.

## Recommendation

Use local `three.js` under its MIT license and implement the STM32F103ZET6 Elite board, pins, wires, and interactions in this project. `JENW1N/ohmlet` is a practical MIT-licensed source for selective reuse or adaptation of small, well-bounded helpers, especially procedural component meshes, ray-based picking, and routed wire geometry. Preserve its copyright and MIT notice with any copied substantial code.

Treat `RephilStudios/Breadboard-3D` as a visual/behavioral reference only. At the reviewed commit it has no `LICENSE` file and GitHub reports no detected license, so the default copyright position does not permit copying or redistributing its code.

No reliably licensed, board-accurate STEP model for the ALIENTEK/Elite STM32F103ZET6 V1 board was found in the focused search. Model the board procedurally from measured dimensions, photographs, silkscreen references, and connector positions. A standard-package model from KiCad can help represent individual components, but KiCad's package library does not supply this complete board.

## JENW1N/ohmlet

- Reviewed commit: [`02a5a72183d1630ff3d52a122414f44feb47fcce`](https://github.com/JENW1N/ohmlet/tree/02a5a72183d1630ff3d52a122414f44feb47fcce)
- License: [MIT](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/LICENSE), copyright 2026 JENW1N.
- Architecture: [ARCHITECTURE.md](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/ARCHITECTURE.md)

Relevant design:

- The scene contract is isolated in [`scene-api.ts`](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/src/three/scene-api.ts), while [`scene.ts`](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/src/three/scene.ts) owns the renderer, camera, lights, board, interaction, and scene lifecycle. This is a useful separation for the lab.
- Procedural visuals are dispatched by [`component-meshes.ts`](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/src/three/component-meshes.ts) into focused builders such as [`ics.ts`](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/src/three/meshes/ics.ts), [`passives.ts`](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/src/three/meshes/passives.ts), and shared mesh helpers. This is the best direct reuse candidate.
- Picking raycasts a plane for placement, snaps the hit to the nearest valid hole, and raycasts component groups carrying IDs in `userData`. The approach is suitable for header-pin picking on an Elite board, with a board-specific pin index replacing breadboard-hole math.
- [`wire-router.ts`](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/src/three/internal/wire-router.ts) is a pure geometry planner without Three.js imports. [`wires.ts`](https://github.com/JENW1N/ohmlet/blob/02a5a72183d1630ff3d52a122414f44feb47fcce/src/three/internal/wires.ts) converts cached routes into Catmull-Rom tube geometry. The separation is strong, but the full collision-aware router is more complex than this lab initially needs; a small endpoint-to-endpoint curve helper is the practical first reuse.

Fit and limits:

- Good fit for Three.js mesh construction, selectable object metadata, pin/hole spatial indexing, wire curves, previews, and scene boundaries.
- It explicitly models a breadboard and has no microcontroller model. Its topology, part catalog, analog solver, board growth, and breadboard routing assumptions do not transfer directly to an STM32 board lab.
- Prefer copying only a clearly identified helper when it materially reduces risk. Record its origin and retain the MIT notice; otherwise reimplement the idea in the project's simpler data model.

## RephilStudios/Breadboard-3D

- Reviewed commit: [`a06fa6923210445259d147237876ca5fe1b03e13`](https://github.com/RephilStudios/Breadboard-3D/tree/a06fa6923210445259d147237876ca5fe1b03e13)
- License: **none found**. There is no root `LICENSE` at this commit, and the GitHub repository license field is empty.
- Main 3D implementation: [`js/scene3d.js`](https://github.com/RephilStudios/Breadboard-3D/blob/a06fa6923210445259d147237876ca5fe1b03e13/js/scene3d.js); geometry/catalog data: [`js/defs.js`](https://github.com/RephilStudios/Breadboard-3D/blob/a06fa6923210445259d147237876ca5fe1b03e13/js/defs.js).

Relevant design:

- A single scene class creates the board and component primitives with `BoxGeometry`/`CylinderGeometry`, attaches selection metadata through `userData`, and raycasts components and wire tubes.
- Wires are Catmull-Rom curves rendered with `TubeGeometry`; each wire remains independently pickable. This is a straightforward behavior reference for clickable jumper wires.
- Its catalog-driven placement and pin metadata are conceptually useful, but scene construction, interaction, and mesh code are comparatively monolithic.

Fit and limits:

- Useful for observing interaction choices and a minimal wire implementation.
- Do not copy code, meshes, or assets without the author's separate permission or a subsequently added license that clearly covers the desired revision.

## three.js

- Upstream: [`mrdoob/three.js`](https://github.com/mrdoob/three.js)
- Reviewed development commit: [`de9e0cb51f6365df73557cecd5cb2551e05f64be`](https://github.com/mrdoob/three.js/tree/de9e0cb51f6365df73557cecd5cb2551e05f64be)
- License: [MIT](https://github.com/mrdoob/three.js/blob/de9e0cb51f6365df73557cecd5cb2551e05f64be/LICENSE).

It is suitable as the local rendering dependency. Keep the distributed license notice. Pin the package version/lockfile used by the project rather than following the development branch implicitly.

## KiCad 3D package library

- Upstream: [`KiCad/kicad-packages3D`](https://github.com/KiCad/kicad-packages3D)
- Reviewed commit: [`b8b3cfdfad88ba66f21002b3de51dc6f7d55ba5a`](https://github.com/KiCad/kicad-packages3D/tree/b8b3cfdfad88ba66f21002b3de51dc6f7d55ba5a)
- License: [CC BY-SA 4.0 with the KiCad Libraries exception](https://github.com/KiCad/kicad-packages3D/blob/b8b3cfdfad88ba66f21002b3de51dc6f7d55ba5a/LICENSE.md).

The exception permits electronic designs and generated design files to use library data without forcing the whole design under CC BY-SA. Redistributing library models, including modified models as a collection, remains subject to attribution and share-alike requirements. Check the model's source metadata as well as the repository license before bundling a specific asset.

This library is relevant for generic packages such as the LQFP-144 MCU body and common connectors. It is not evidence of an accurate Elite V1 full-board model. For a self-contained browser simulator, procedural low-poly packages are likely smaller and easier to label, select, and visually simplify.

## Elite V1 board CAD search result

The focused GitHub/web search did not find a complete ALIENTEK/Elite STM32F103ZET6 V1 STEP/WRL model with an explicit reusable license. ST provides device and evaluation-board documentation, but the ST `STM3210E-EVAL` board is a different board, and an STM32F103ZE package model represents only the chip. Product-page downloads, forum attachments, and CAD aggregation sites should not be treated as reusable unless the asset itself carries a clear license and matches the exact board revision.

For this project, create an intentionally recognizable procedural board: PCB outline and thickness, dual header rows with named pins, LQFP package, crystals, buttons, LEDs, USB/power/connectors, and silkscreen zones. Document that it is a teaching visualization rather than manufacturing CAD.
