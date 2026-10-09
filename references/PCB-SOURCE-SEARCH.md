# ALIENTEK Elite STM32F103 PCB source search

Checked 2026-10-09. This was a bounded, read-only search for actual editable PCB source, Gerber, or manufacturing files for the ALIENTEK/正点原子 精英 STM32F103 board. Claims from search-result pages were not treated as proof of file contents.

## Result

No verified, downloadable original ALIENTEK Elite V1/V2 PCB routing source or Gerber set was found.

The strongest official source is an ALIENTEK download index pointing to a Baidu “A disk.” The official index does not enumerate its contents, and the current share could not be opened far enough to inspect individual files. A third-party file-list index shows an A-disk folder named `7，硬件资料` and a separate folder named `3，ALIENTEK精英STM32F103开发板原理图`, but that is evidence of hardware documentation and schematic material, not proof of `.PcbDoc`, Gerber, or original routing data.

A community EasyEDA Pro project provides editable schematic and PCB data under GPL 3.0, but its author says it was redrawn from the ALIENTEK schematic, changes multiple circuits and peripherals, and uses the author's own routing. It is useful as a topology/layout reference, not as the Elite board's original PCB route.

## Official ALIENTEK Products index

- Repository: [`alientek-openedv/Products`](https://github.com/alientek-openedv/Products)
- Reviewed repository commit: [`d917adac269f72ea1fb008baaed4d25319fcdf0c`](https://github.com/alientek-openedv/Products/tree/d917adac269f72ea1fb008baaed4d25319fcdf0c)
- Exact Elite index revision: [`862ffceb253819854cfef7180419e471a29439da`](https://github.com/alientek-openedv/Products/blob/862ffceb253819854cfef7180419e471a29439da/zdyz_docs/boards/stm32/zdyz_stm32f103_jingying.rst)
- Repository contents at the root: only `README.rst` and `zdyz_docs/`; there is no board CAD payload.
- License: GitHub reports no repository license, and no root license file was found. “资料开源免费” in the organization description is not a software/hardware license grant.

The Elite page is a link catalog. It provides:

- Official A-disk share: [Baidu Pan](https://pan.baidu.com/s/1_FxkgE8RA6fU9qcUa7GPPA), extraction code `cr9e`.
- Product discussion thread: [openedv thread 308946](http://www.openedv.com/thread-308946-1-1.html).
- Videos and teaching material links.

It does **not** list `.PcbDoc`, `.SchDoc`, `.PrjPcb`, Gerber, ODB++, drill, pick-and-place, or BOM files. The GitHub tree contains only the RST catalog page and product image for this board, not source CAD.

During this check, the Baidu share landing page was reachable and exposed the share identifiers, but password verification returned an error and no file listing or download URL could be obtained. Therefore the A disk is an official lead, but its current accessibility and exact hardware-file inventory remain unverified.

## What can be verified about the A disk

A third-party indexed file listing, [“精英板 资料盘(A盘)”](https://www.xuebapan.com/info/275ceed4f42f04a2d1865706163ea180.html), records these top-level names:

- `7，硬件资料`
- `3，ALIENTEK精英STM32F103开发板原理图`
- teaching documents, source examples, software, and reference material

This is consistent with the official A-disk description, but the index does not expose the contents of `7，硬件资料`. It cannot establish that editable board routing or fabrication data is present. The explicitly named schematic folder likely contains viewable schematic documentation; it should not be described as PCB source without inspecting its actual extensions.

No reliable board revision can be assigned from these sources. The official page calls the product simply `stm32f103精英开发板`; it does not label the download V1 or V2. Any later file obtained from the share must be matched against the physical board's silkscreen revision before use.

## openedv GitHub organization

The newer official [`openedv`](https://github.com/openedv) organization hosts many ALIENTEK product repositories, but the inspected public repository listing/search produced no Elite STM32F103 hardware repository. Its presence does not provide an original Elite PCB source.

## Community EasyEDA project: w1234533/stm32

- Project: [STM32 by w1234533](https://oshwhub.com/w1234533/stm32)
- Platform format: EasyEDA/嘉立创 EDA **Professional** project, opened or cloned through the platform editor.
- License shown by the project page: GPL 3.0.
- Created: 2022-10-14; last updated: 2023-02-13.
- Available design data: the project page states that the schematic and PCB are visible by opening it in the editor. The project has no generated static design preview, no populated 3D-model section, and no listed downloadable attachments.

The author explicitly describes this as a self-drawn 10 × 10 cm board based on the ALIENTEK Elite schematic. It retains roughly 99% of the peripherals but changes the design, including Type-C connectors, CH340C, added gyro/ESP8266/OLED/RGB LED interfaces, removal of the capacitive key, switch changes, and SWD in place of JTAG. The author also states limited PCB-routing experience.

Consequences:

- It is real editable schematic and PCB data, subject to the platform's clone/editor workflow.
- It is **not** an original ALIENTEK source file, a faithful V1/V2 PCB copy, or evidence of ALIENTEK routing.
- Its placement and routing may be studied as a GPL community design. Reusing it in distributed project assets requires honoring GPL 3.0 and also considering the platform page's additional “learning/research, no commercial sale” notice, which creates licensing ambiguity beyond plain GPL. Do not bundle or copy it without resolving those terms.
- For the simulator, it can help cross-check functional blocks and approximate density. It should not determine the visual board outline, connector coordinates, silk labels, or copper routing of an original Elite board.

## Community V2-compatible core-board project

[STM32F103ZET6 核心板 兼容正点原子精英版V2](https://oshwhub.com/haoshuaizuishuai/stm32f103zet6-he-xin-ban) is another editable EasyEDA Pro project under GPL 3.0. It explicitly claims connector-level compatibility with Elite V2 while documenting substantial changes: a two-layer board, modules moved to a separate baseboard, BOOT switches, a CH340K substitution, and revised JTAG/SWD handling. The page exposes schematic sheets and a PCB in the platform editor, but it is a compatible redesign, not the original complete Elite V2 board.

This project may be the better community reference when the simulator needs the V2 header interface, but its board geometry and route still must not be presented as ALIENTEK's original.

## File-type conclusion

| Source | Schematic | Editable PCB | Gerber/fab files | Original Elite routing | License status |
|---|---:|---:|---:|---:|---|
| ALIENTEK GitHub `Products` | Link only | No | No | No | No repo license |
| Official A disk | Likely, based on named folder | Unverified | Unverified | Unverified | No explicit license verified |
| `w1234533/stm32` | Yes, platform editor | Yes, platform editor | Not listed | No; modified redraw | GPL 3.0 shown, plus platform noncommercial notice |
| V2-compatible core board | Yes, platform editor | Yes, platform editor | Not listed | No; compatible redesign | GPL 3.0 shown, plus platform notice |

## Recommendation for the 3D simulator

Do not wait on or claim use of original ALIENTEK routes. Use the official schematic/documentation to identify functional blocks and pin names, and use photographs plus measured board dimensions for component placement. Copper traces can be omitted, stylized, or clearly labeled as illustrative. If an exact route layer becomes important, first obtain the official A-disk files manually, inspect the filenames and formats, confirm the board revision, and locate an explicit license or written permission covering redistribution/derivative use.

The community EasyEDA boards are suitable references for understanding how the same functional blocks can be placed and routed. They are not suitable as hidden substitutes for the original board design.
