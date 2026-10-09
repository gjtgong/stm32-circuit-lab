# 首版验收记录

2026-10-09，Asia/Shanghai。

| 任务 | 结果 | 证据 |
|---|---|---|
| T1 目标与首版范围 | accepted | STM32F103ZET6，逻辑引脚与接线；512 KiB Flash、64 KiB RAM |
| T2 内核研究 | accepted | Renode 官方平台与外部控制 API；完整芯片外设不作支持声明 |
| T3a 编译/执行 | accepted | 外部控制协议首次失败后修复；后端 4 项测试通过；Flash 向量表 0x08000000 |
| T3b 模块库与界面 | accepted | 浏览器实际搜索、添加、拖入、删除、连接引脚与本地保存 |
| T3c 执行器响应 | accepted | 8 项模型测试；第二轮补充脉宽容差、双通道状态保持和最终计数积分 |
| T4 联合验收 | accepted | PB0 HIGH 点亮 LED；删去 GND 线时 LED 熄灭而 PB0 不变；舵机真实轨迹 201 次变化与目标180°；电机真实方向轨迹与±3000rpm理想响应 |

模型分工：主模型 gpt-6.1-sol（用户所选强度）负责范围、界面和最终验收；研究 gpt-5.6-sol low；后端与响应模型 gpt-5.6-luna max。

尚未完成的完整平台功能：MPU6050/OLED/超声波通信模型、编码器脉冲回注 MCU、USART RX、硬件定时器 PWM、完整 HAL/CubeMX 多文件项目导入与各类外设模型、PCB CAD 和生产文件。首版仅为部分能力可运行的原型；这些模块在界面明确标注支持状态。

测试命令见 README。后端仅绑定本机回环地址，未发布外网、未烧录任何实体板。

## 2026-10-09 publication check

Local workspace: 16 Python tests and 18 Node tests passed. CAD checks use locally acquired board data. Public checkout needs `python3 tools/fetch_open_board.py` before CAD tests, and external ARM GCC/Renode before firmware execution tests. Power LED visual state was checked in browser, including off/on; it is an ideal supply visualization, not a SPICE result.

Optimization: JS module syntax check, 6 converter tests and 3 CAD mapping tests passed. Browser verified complete board/modules/wires, package mark, MCU leads and off/on power LED; no new console errors after external-LED reference fix. Existing source photos/manuals and third-party board geometry remain local only.

## Gerber connectivity follow-up

16 Gerber tests and 12 source-geometry tests passed. Ordered copper images resolve the prior GND candidate; 0 seeded net conflicts, 0 disconnected known nets, 0 missing/partial seeds. 96 unassigned copper clusters remain for review. See reports/GERBER-CHECK-2026-10-09.md; this is not a full electrical or manufacturing verdict.

## Copper issue viewer follow-up

Gerber reports now export unassigned island polygon rings with layer and stable report IDs; a hole-preservation test verifies exported area. A loopback GET /api/pcb-check serves the report only if all three source hashes still match. A report test verifies changed-source and unexpected-path rejection. Browser verified 96 sorted entries, top/bottom selection, polygon highlighting, and clearing restores components/camera without editing firmware or six saved wires. Underside fill lighting improves inspection. No automatic fault verdict or current simulation is added.

Final follow-up regression: all 46 Python tests and 18 Node tests passed. Module syntax and git diff whitespace checks passed.

## Copper provenance follow-up

7 provenance tests and 18 Gerber tests passed. All 96 unassigned network clusters remain listed:88 source copper-text associations,8 artwork associations covering6 unnamed pads. Source drill records confirm SW1 planned1mm holes; no physical drilling simulation added. Matching is same-layer path/footprint geometry, not a text bounding box. Extra copper and unsupported formats remain unresolved; associations never remove conflict/open findings. UI adds source IDs, coverage, pad identity/text and planned drill; source PCB hash also checked against loaded CAD metadata.

Follow-up focused regression:7 provenance +18 Gerber +12 source geometry +1 report tests passed (38 total). JS module syntax and diff checks passed. Browser verified SW1-1 drill annotation, U2-106 pad identity, and copper text784520A;0console errors. Closed copper-font contours now render as filled source glyphs, and the inspector is taller for readable evidence.

## Schematic/PCB terminal comparison

17 schematic tests +2 report freshness tests passed. Local source graph:366 pins,504 wiresegments,286 labels,6NC markers;364 matched PCB terminals,0 network differences in matched subset.6unnamedpads have explicit NC intent. BOOT1/BOOT mapped only by same source component ID;X1:1/2 and16unreferencedpads remain unverified;3alias groups retained for review. In-memory real PCB pin-net change and real NC marker deletion detected. No device-datasheet/electrical/ERC verdict. API serves source-hash-verified report; browser selected U2-106 and showed NC intent and unresolved summary.

Final regression:72 Python +18 Node tests passed; JS syntax/diff checks passed. Browser U2-106/SW1 NC evidence and clearing/reselecting verified,0console errors; existing code and6wires preserved.

## Drill geometry follow-up

77 Python and 21 Node tests passed, including actual source/Excellon slot and NPTH correspondence, a drilled-away trace causing an open, and a slot-end trace avoiding a false pad short. Browser verified open mounting holes, corrected round silkscreen size and drilled pad meshes; saved code and six wires retained. Source circle radius conversion follows the official EasyEDA PCB format; independent HOLE radii verified against NPTH manufacturing output.

CLI now subtracts219 PTH hits (including7 G85 slots) and7 NPTH hits from both Gerber images before connectivity audit. Known-network findings remain0 conflicts/0 opens/0 missing or partial seeds;96 unassigned clusters remain listed,22.466415mm² after drilling. Report hash guard now includes both drill files and rejects changes to any of five inputs. Strict bounded Excellon parser rejects unsupported modes/routing/units and incomplete files. No plating/tolerance/current/thermal or whole-board safety verdict. X1 identity and16 unreferenced pads remain unresolved.
