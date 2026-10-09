# STM32 Circuit Lab

本地运行的 STM32F103ZET6 代码、开发板与接线仿真工作台。

## 启动

```bash
git clone https://github.com/gjtgong/stm32-circuit-lab.git
cd stm32-circuit-lab
python3 tools/fetch_open_board.py
python3 server.py
```

打开 http://127.0.0.1:8765 。需要 `arm-none-eabi-gcc` 与 Renode；本机便携 Renode 位于 `runtime/renode/`。后端缺失时明确报错，不产生模拟轨迹。

## 使用

1. 编辑左侧 `main.c`，或加载闪灯示例。
2. 搜索模块；拖到画布或点击添加。模块允许多个实例。
3. 点击两个引脚连接导线，拖动模块移动，选中导线/模块后删除。
4. 编译并仿真。编译器生成真实 Cortex-M3 ELF，Renode 执行，界面按虚拟时间回放采集到的 GPIO 变化。
5. 按键、数字传感器的输入可在模块属性中切换；重新运行后应用。
6. 导出 JSON 保存代码、模块实例、位置与接线；可再次导入。浏览器自动保存一份本地项目。

## 工程导入接口

`POST /api/run` 保持原有的单文件 `code` 请求，也可以选择下面两种固件
输入之一；同一个请求只能提供一种：

- `files`：相对路径到 UTF-8 文本的对象，例如
  `{"main.c":"#include \"helper.h\"...", "helper.h":"...", "helper.c":"..."}`。
  最多 32 个 `.c`/`.h` 文件，文件内容合计最多 512 KiB；路径不能是绝对路径、
  不能包含 `..`，后端会在临时工程目录中编译全部 `.c` 文件并链接本地启动代码。
- `elfBase64`：外部工具链生成的 ARM ELF32 小端可执行文件的严格 Base64。
  ELF 必须在 `0x08000000..0x0807ffff` 闪存和 `0x20000000..0x2000ffff` SRAM
  范围内，且在物理闪存 `0x08000000` 提供有效 Cortex-M 向量表；不接受任意
  主机可执行文件、压缩包或超出本地 Renode 内存模型的映像。

两种工程导入最终都进入同一套 Renode 外部控制与 GPIO 事件采集路径，因此返回
格式仍为 `{ok, events, serial, log, durationMs}`。导入工程不扩大当前外设边界；
ADC、USB、CAN、SDIO、SPI、I2C、DMA 和硬件 PWM 仍未在本地板卡模型中实现。

默认电路：PB0 → 330Ω 电阻 → LED A；LED K → GND。按键 PA0 → 按键 → 3V3。删去 LED 接地线后灯不会亮。

实验下拉菜单可加载“LED 闪灯”“舵机 PWM”“电机正反转”三套代码与完整接线。舵机与电调需要 5V/GND 以及控制信号；电机经 TB6612 的 A01/A02 接入。电机属性可设置最大理想转速和编码器 PPR。

串口终端的 RX 接 PA9，GND 接 GND，可查看 USART1 输出。串口接收与波特率误差建模未实现。

## 当前板卡与边界

当前显示 PE.JADO 的 STM32F103ZET6 最小系统板。焊盘、铜轨、丝印与元件位置来自公开 EasyEDA PCB / Gerber；3D 元器件外形按封装尺寸近似重建，并非原厂 STEP 模型。网络可选中高亮，支持查看顶层/底层铜轨。

板载 LED1 是 3.3V 电源指示灯，不能由 GPIO 实现呼吸灯。顶部通断电按钮控制理想电源与 LED 外观，目前不求解电流，也不与 Renode CPU 生命周期联动。芯片 ST Logo 使用矢量轮廓；顶面字体为视觉近似，不代表原厂字体文件。

尚未实现 PCB 短路、间距、开路 DRC/ERC，以及 SPICE、电源完整性、热分析；不可据此断言实物打板一定能工作。旧版精英板代码保留用于兼容，厂商照片和资料副本不随仓库发布。

GPIO A–G 和串口发送由真实固件驱动。电阻按数字导通处理，不计算电流、电压或损坏。运行期间不做交互式输入，输入快照在每次运行开始时注入；每次运行采集 2 秒虚拟时间，再回放一次。

IMU、超声波和 OLED 有模块外观与引脚定义，但尚未实现其通信协议；界面明确标识。电机类响应模型属于理想控制信号响应，不等于真实动力学；编码器反馈回注 MCU 的闭环仿真尚未实现。任意 HAL/CubeMX 项目的外设行为、硬件定时器 PWM、ADC、USB、CAN、SDIO、SPI、完整 RCC/AFIO 时钟树目前不在已验证支持范围内；工程导入只负责受限地编译多文件 C 或加载通过内存映射校验的外部 ELF。

## 文件

- `server.py`：本地 HTTP、编译、Renode 生命周期与采集。
- `firmware/`：启动代码、链接脚本、寄存器辅助头。
- `runtime/`：平台模型、外部控制协议适配、便携运行时。
- `static/`：界面、V1 实物照片与物理引脚映射、模块库、接线与轨迹回放。
- `examples/`：可运行固件示例。
- `tests/`：真实执行和响应模型检查。

内核参考：[Renode](https://renode.io/)、[外部控制 API](https://renode.readthedocs.io/en/latest/api-description/external-control.html)、[STM32F103ZE](https://www.st.com/en/microcontrollers-microprocessors/stm32f103ze.html)。

## 已验证证据

- 真实 ARM ELF 的向量表位于 `0x08000000`，Renode 通过同一 Flash 对象的零地址别名启动。
- 后端 4 项测试通过：编译与 ELF、编译错误、延时改变真实轨迹、GPIO 输入影响固件。
- 执行器模型 8 项测试通过：供电、PWM/角度、方向、无输入无活动、估算与脉宽误差。
- 浏览器联调：模块拖入与接线成功；PB0 HIGH 点亮 LED，删去接地线后 LED 熄灭而 PB0 保持 HIGH；电机正反转和舵机目标 180° 显示通过。

```bash
python3 -m unittest discover -s tests -p 'backend*.py' -v
node --test tests/actuators.test.cjs
```

画布操作：滚轮以鼠标位置为中心缩放；拖动空白区域平移；按住鼠标中键可从任意位置平移。右上角提供放大、缩小和复位视图按钮。

## 依赖与测试

Python 3.10+、`arm-none-eabi-gcc` 和 Renode 1.16.1。Renode 二进制不随仓库发布；从 [Renode 官方发布页](https://github.com/renode/renode/releases) 安装，设置 `RENODE_BIN` 为可执行文件路径，或解压到 `runtime/renode/`。前端 Three.js 已随附，无需 npm 构建。

```bash
python3 -m unittest discover -s tests -p '*test.py'
node --test tests/*.test.cjs
```

## 开源与来源

应用代码以 GPL-3.0-only 发布。第三方 PCB 原文件和派生几何因再分发条款待确认，未随仓库发布；启动前运行获取工具从原来源下载并转换，仅在本地生成。见 [板卡来源](references/OPEN-BOARD-SOURCE.md)。Three.js / OrbitControls / SVGLoader 使用 MIT，许可证见 `static/vendor/THREE-LICENSE`；ST Logo 矢量来自 Simple Icons（CC0），商标权仍属于 ST。厂商 PDF 只引用链接，不随仓库发布。完整说明见 [第三方声明](THIRD_PARTY_NOTICES.md)。

## 实验性 PCB 几何检查

```bash
python3 -m pip install -r requirements-check.txt
python3 tools/pcb_check.py --clearance 0.15
python3 -m unittest discover -s tests -p 'pcb_check_test.py'
```

检查铜轨、RECT/ELLIPSE/OVAL 焊盘、过孔以及可解析的直线实体铜区域。输出异网同层相交、指定间距不足、同网焊盘不连通的候选；金属化通孔跨层连通，异层交叉本身不会报短路。CLI 报告在本地 `reports/pcb-check.json`，不随仓库发布。尚未接入网页问题标记界面。

**这是部分几何审计，不是全板通过/失败判定。** 覆铜边界不等于实际填铜，当前未解析覆铜、铜层文字和区域 cutout；实际板 GND 断连候选可能由缺失地平面数据造成。圆弧使用多边形近似；0.15mm 是本次测试阈值，不代表来源板的制造规则。没有检查原理图与 PCB 网络一致性、电压、电流或元件电气模型。


### 实际 Gerber 覆铜连通性复查

```bash
python3 tools/gerber_check.py
python3 -m unittest discover -s tests -p 'gerber_check_test.py'
```

此工具按绘制顺序处理 dark/clear 极性、区域多轮廓、圆形/矩形孔径的线段和闪绘，使用焊盘/过孔标注匹配实际铜岛网络。只支持绝对毫米坐标和直线，遇到未支持命令会拒绝解析。格式依据 [Ucamco Gerber 规范](https://www.ucamco.com/en/guest/downloads/gerber-format)。

本次源板复查消除了源几何模式中的 GND 断连候选；已匹配网络未发现冲突或断连，但还有 96 个未匹配网络的铜块，需要人工审查。**不代表整板通过电气或制造验证。** 无网络名的 Gerber 依赖源 PCB 标注推断网络，尚未检查间距、电流或元件电气行为。详见 [复查报告](reports/GERBER-CHECK-2026-10-09.md)。本地详细 JSON 不随仓库发布，网页标记尚未接入。
