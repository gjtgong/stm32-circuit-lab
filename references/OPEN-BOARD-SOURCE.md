# Selected open STM32F103ZET6 board source

Acquired 2026-10-09 from the public [PE.JADO STM32F103ZET6 minimum-system-board project](https://oshwhub.com/PE.JADO/stm32f103zet6). The project page identifies the design as GPL 3.0, created 2020-10-22 and updated 2022-02-09. It is an original small STM32F103ZET6 board, not an ALIENTEK Elite clone.

## Acquired files

All files are in [`references/open-board/`](./open-board/); hashes are recorded in [`SHA256SUMS`](./open-board/SHA256SUMS).

- `EasyEDA_F103ZET6.Pcb.api.json`: public EasyEDA Standard PCB document API response. `result.dataStr` is the editable PCB source, including 1,243 shapes, footprint and pad data, named nets, traces, vias, copper, board outline, and top/bottom silkscreen. Document UUID `907173c2f4454257912bca00dd03fb97`, title `F103ZET6.Pcb`, document type 3, EasyEDA editor version 6.4.7.
- `EasyEDA_project-with-schematic.api.json`: public EasyEDA project/schematic API response. The editable schematic is at `result.schematics[0].dataStr`; schematic UUID `df3967fc719349dcaa806c0739779f4c`, master data ID `77fa72e48f9b4a9d90c775f8b14ae12e`, editor version 6.4.7.
- `Schematic_STM32F103ZET6_minimum_2020-10-22.pdf`: original page attachment. The page declares MD5 `690157d2f84c699452d7af89eef77375`, which matches the downloaded file. One A3-landscape page, revision 1.0, dated 2020-10-20.
- `Gerber_F103ZET6.Pcb.zip`: original page attachment. The page declares MD5 `8d81f1cf507da2b0e486c2140381c648`, which matches. It contains top/bottom copper, top/bottom silkscreen, paste and solder masks, plated and non-plated drill files, and board outline. The extracted copies are in `open-board/gerber/`.
- `LICENSE-GPL-3.0-only.txt`: GPL-3.0-only text from the SPDX license-list-data repository. The project page labels the project “GPL 3.0”; it does not state “or later,” so this acquisition conservatively records GPL-3.0-only pending the lead's final licensing decision.

Attachment URLs verified and used:

- [schematic PDF](https://image.lceda.cn/attachments/2020/10/a5gZqbBmXoF8BQhRvdQzOZpR43ipEnr4o5GvTEJ5.pdf)
- [Gerber ZIP](https://image.lceda.cn/attachments/2020/10/Prt1H39DksJuqZcLZs3Q1P6nza6MfBJSmyEBZpXE.zip)
- [PCB document API](https://lceda.cn/api/documents/907173c2f4454257912bca00dd03fb97)
- [project and schematic API](https://lceda.cn/api/documents/df3967fc719349dcaa806c0739779f4c)

## Geometry and coordinate use

The Gerber outline declares millimetres with absolute `3.3` coordinates. Its rectangular boundary is `(0,0)` to `(56.098,53.500)` mm. This is the most convenient coordinate frame for the simulator: take lower-left as `(0,0)`, X rightward, Y upward, then invert Y only if the Three.js board convention requires it.

The EasyEDA source uses its own canvas coordinates (`head.x=4020`, `head.y=3272`; PCB `BBox` approximately `x=4015.7`, `y=3451.9`, `width=235`, `height=232.6`). Preserve these values when parsing the JSON and derive a single affine transform by matching the source board-outline primitives to the Gerber 56.098 × 53.500 mm outline. Do not assume raw EasyEDA canvas values are millimetres.

The board is a two-copper-layer design. Its Gerbers provide visually accurate trace surfaces and silkscreen. The editable PCB JSON adds the net and component identity that Gerber lacks, so it should be the primary source for selectable pins and traces; use Gerber as a rendering and dimensional cross-check.

## MCU, headers, and LED

The design uses `U2`, STM32F103ZET6 in LQFP-144. Eight 1×15 headers are arranged as four paired banks: `H1/H2`, `H3/H4`, `H5/H6`, and `H7/H8`. A separate four-pin `H9` exposes `3V3`, `SWCLK`, `GND`, and `SWDIO`.

The schematic records these paired header signals, pin 1 through 15:

- `H1`: BAT, PE2, PE3, PE4, PE5, PE6, PC13, GND, GND, GND, PC3, PA0, PA1, NRST, GND.
- `H2`: GND, 3V3, PA3, PA4, PA5, PA6, PA7, PE11, PE12, PE13, PE14, PE15, PB10, PB11, 3V3.
- `H3`: PC5, PB0, PB1, PB2, PF11, PF12, PF13, PF14, PF15, PG0, PG1, PE7, PE8, PE9, PE10.
- `H4`: PA2, PF10, PC2, PC1, PC0, PF9, PF8, PF7, PF6, PF5, PF4, PF0, PF1, PF2, PF3.
- `H5`: PB3, PG15, PG14, PG13, PG12, PG11, PG10, PG9, PD7, PD6, PD5, PD4, PD3, PD2, PD1.
- `H6`: PA14, PA15, PC10, PC11, PC12, PD0, PB4, PB5, PB6, PB7, 3V3, PB8, PB9, PE0, PE1.
- `H7`: PC8, PC7, PC6, PG8, PG7, PG6, PG5, PG4, PG3, PG2, PD15, PD14, PD13, PD12, PD11.
- `H8`: PA13, PA12, PA11, PA10, PA9, PA8, PC9, PD10, PD9, PD8, PB15, PB14, PB13, PB12, +5V.

`LED1` is only the 3.3 V power indicator: `3V3 → LED1 → R1 1 kΩ → GND`. It is not driven by an MCU GPIO and should illuminate whenever the simulated 3.3 V rail is powered. The board has reset switch `SW2`, power switch `SW1`, an 8 MHz HSE crystal, a 32.768 kHz LSE crystal, BOOT selection header, Micro-USB power input, and three M3 mounting holes.

## Fit and limitations

This source set meets the simulator's need for readable copper, exact silk, component positions, named nets, and pin coordinates. It represents a minimal system board, so it has fewer teaching peripherals than an Elite board. Any added user LED, sensors, display, or expansion modules should be modeled as external parts rather than attributed to this PCB.

The GPL label is clear on the public project page, but hardware-project licensing and the platform's general reuse notice can still affect redistribution. The lead should decide whether the shipped application bundles derived board geometry/source or merely consumes the acquired files during development. Keep attribution to PE.JADO and this provenance record with any distributed derivative.
