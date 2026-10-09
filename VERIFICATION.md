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
