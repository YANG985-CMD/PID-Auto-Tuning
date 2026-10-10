# STM32G4 CAN 通信路径

## 板卡资料包含两个版本

以下信息来自对用户本地原理图的逐图检查。它们是候选板卡资料，不是已经确认的实物丝印；不能根据“两根 CAN 引脚”认定具体版本。

| 项目 | 较旧的《STM32G4开发板原理图》 | 《SCH_STM32G431RBT6_BLDC_V1.3》 |
|---|---|---|
| CAN TX / RX | PA12 / PA11 | PB9 / PA11 |
| 收发器 | L9616-TR | SN65HVD1050DR |
| 图中 CAN 接口 | H17：7=CAN_H，8=CAN_L，1=AGND | P4：2=CAN_H，1=CAN_L，3=AGND |
| 图中终端 | R15，120 Ω | R50，120 Ω |

特别纠正：**H17 的 CAN 引脚不是 12/13**。相邻 H16 的标号不属于 H17。本项目不上传厂商原理图或其截图；实际接线应按实物 CAN_H/CAN_L/GND 丝印和对应板卡版本核对。

V13.1 手册第十二章的经典 CAN 示例使用 500 kbit/s：`160 MHz / 20 / (1 + 10 + 5)`。USB-CAN 模块资料描述 PCAN 固件；本次电脑驱动确实识别到 PCAN-USB，且能力查询 `supports_fd=false`。当前适配器按经典 CAN 使用，不能假设它支持 CAN-FD。

## 实物照片核对结果

用户于 2026-10-10 提供的整体照片与本地套件接线图布局相符：USER1、USER2、USER3、RESET 四个按键，蓝色电位器，以及调试/UART/CAN 共用的 8 针排针。随后提供的排针近照和用户说明确认了 **H/L 是板端 CAN 接口**；相邻丝印为 PB11、PB10、SWDIO、SWCLK、3.3V、GND。这对应较旧原理图的 H17 排针布局，可以按实物 H/L 核对接线，不再要求用户辨认 H17/P4 编号。

| 电机板实物标记 | 连接到 USB-CAN |
|---|---|
| H | H / CAN_H |
| L | L / CAN_L |

USB-CAN 照片显示欧拉 USBCAN / PCAN 模块和 120R 标记，与套件资料及电脑的 PCAN-USB 识别结果相符。照片不能确认导线两端的电气连续性、完整 MCU 型号、PCB 版本号、收发器完整型号或模块终端跳帽是否有效。**布局核对通过不等于整张旧原理图与实物逐件一致。** 私人照片和厂商接线图没有上传公开仓库。

### 为什么 MCU 亮灯，CAN 仍可能没有供电

对应布局的旧原理图中，CAN 收发器 VS 接 **+5V**；电源链为 `VDC → +12V → +5V → +3.3V`，调试排针只有 3.3V 供电脚。给调试排针 3.3V 可以让 MCU 工作，但不能由此推定 5V 电源也正常；板上的 3.3V 电源指示灯和 USB-CAN 模块指示灯均不能代替板端 5V 测量。

这曾是零帧记录的一个待验证原因，没有被确认为故障。套件 V13.1 手册 PDF 第 92 页 CAN 实验明确画出开发板 24V/3A 供电，电脑 USB 只为适配器供电。随后在用户确认板端供电的条件下，用独立 CAN 专用 RAM 程序完成了 16 组双向收发；电机保持接线，功率输出检查通过。功能测试没有取得 5V 电压测值，不能代替电压精度检查。不直接给未知电源脚注入电压。

## 当前状态

对应板上 Flash 的 `17.PID control speed` 工程已经包含 FDCAN。2026-10-10 再次通过 STLink 只读比较，Intel HEX 的全部 33,500 字节程序记录与板上 Flash 一致。本次没有烧录。

- `fdcan.c`：经典 CAN、500 kbit/s、正常模式、关闭自动重发，GPIO 使用 PA12/TX 和 PA11/RX。
- `main.c`：调用 `MX_FDCAN1_Init()`、`FDCAN_Config()`，约每 10 ms 尝试发送扩展 ID `0x1B`、DLC=8 的帧。
- `TxData[8]`：初始化为零，工程没有把速度、电流或母线测量写入该缓冲区，故它是占位载荷，不能解释成有效电机遥测。
- `stm32g4xx_it.c`：接收数据存入 `RxData`，没有 TD3 增益、停止命令、序号应用确认或租约处理。
- UART3 的 24 字节 Hall 遥测仍是另一路数据，布局见 [legacy-board-telemetry.md](legacy-board-telemetry.md)。

因此，先前“原固件没有启用 FDCAN”的说法已更正为：**已初始化 CAN，但没有实现 TD3 协议**。源码的 PA12/TX 与新版原理图的 PB9/TX 不同；后续实际收发已验证 PA11/PA12 配置可以通信，完整 PCB 版本及收发器完整型号仍未确认。

另外核对了 `8.CAN` 与 `4.BLDC_hallsensor_CAN`：前者的相同扩展 ID `0x1B` 载荷包含母线电压，后者有电机启停解码，均不能直接套用于当前 PID 固件。详细比较及独立诊断结果见 [CAN 实测与原因分析](stm32g431-can-diagnostics.md)。

仓库中的 [can_monitor.py](../scripts/can_monitor.py) 使用 `python-can` 提供的 PCAN-Basic 绑定，只支持经典 PCAN USB。它在初始化通道**之前**设置 Listen-Only 并核验返回值和读回值；初始化后再次读回。设置失败、模式关闭、通道占用或接收错误时拒绝继续，不回退到主动模式。不调用 CAN Write、WriteFD 或 Reset，也不访问 MCU。

`--probe` 只查询适配器能力，不初始化通道；捕获必须显式加 `--allow-live`。原始帧写到标准输出，结束摘要写到标准错误。适配器时间不是 MCU 的 `t_apply_us`，这些原始帧不能直接喂给 TD3。

```text
python -m pip install -r scripts/requirements-can.txt
python -B scripts/can_monitor.py --probe
python -B scripts/can_monitor.py --channel PCAN_USBBUS1 --bitrate 500000 --duration 10 --allow-live
python -B scripts/test_can_monitor.py
```

## 接线和上电顺序

1. 保持电机 24 V 功率电源断开，按已确认的实物 H/L 丝印连接 H→H、L→L；参考地/隔离按模块说明核对，不能把旁边 PB10/PB11 的 UART TX/RX 接到 CAN_H/L。
2. 先确认模块识别为 PCAN，关闭 PCAN-View 及其他可能发送帧的程序。
3. 全部断电后核对总线终端。资料中板端均有 120 Ω，另一端是否接终端取决于模块设置和总线拓扑，不能盲目再并第三个终端。
4. 确认板端收发器逻辑电源。USB/STLink 能给 MCU 供电，不证明 CAN 收发器 5V 已存在。需要按手册给板端供电时，先准备经核对的 CAN 专用程序、保持原应用暂停和功率输出禁能，再由现场确认实际供电状态。
5. 500 kbit/s 静默监听适用于只读观察，但 Listen-Only 不提供 ACK；总线只有 MCU 和监听器时，发送可能不获应答。零帧或 ACK 错误不能单独证明接线坏。正常模式收发使用 [专用 SRAM 诊断](../skills/motor-td3-serial-tuning/references/stm32-can-diagnostics.md)，在授权、供电与输出状态明确后执行。

## 2026-10-10 本次验证

早期监听的结构化结果见 [监听与板卡审计摘要](../examples/stm32g431-can/summary.json)。后续结果见 [内部回环](../examples/stm32g431-can-loopback/summary.json) 和 [实际双向收发](../examples/stm32g431-can-echo/summary.json)；未上传原始私有工程、Flash 内容或设备序列号。

- PCAN 驱动能力查询成功：PCAN-USB、经典 CAN、通道可用。
- 初始化前和初始化后的 Listen-Only 都读回为开启；500 kbit/s 监听约 5.14 秒，收到 0 帧，随后释放适配器。
- 9 项无硬件故障测试通过，包括模式设置失败、通道占用、错误比特率、模式被更改、接收错误和关闭清理。
- 本次未发送 CAN 控制命令、未恢复 MCU 运行、未写 Flash。重新核对 MCU 时发现它已处于运行状态，原固件 `Motor_state=255` 且功率输出使能；无法确定谁或什么使其恢复。Codex 随即暂停、复位并核对 `CR1/CCER/BDTR=0`，结束保持核心暂停。用户确认 24 V 已断开。
- 后续照片已确认板端 H/L 丝印及 8 针排针布局，并识别到配套欧拉 USBCAN / PCAN 模块。MCU 只读复查仍为暂停，TIM1 的 CR1/CCER/BDTR 均为 0。
- 早期监听阶段没有验证板端 CAN 收发；禁止把当时的 0 帧记录解释为电机控制通信成功。
- 后续控制器内部回环 64/64 通过，包含标准/扩展 ID 与 DLC 0～8；修正了诊断软件的标准 ID 掩码错误。
- 用户确认开发板 24V/3A 已接，电机保持接线。专用 CAN SRAM 程序完成 500 kbit/s 下的 16/16 请求和回包，标准 ID 为 `0x6E0/0x6E1`。TIM1 没有启用；最终核心暂停、PWM/GPIO 关闭、完整 128KB Flash 未变、适配器释放。用户随后确认 24V 已断开。
- 因而实际双向链路已验证；5V 测值、完整 PCB 版本、生产应用协议和 TD3 实机通信仍未验证。测试程序及解释见 [实测报告](stm32g431-can-diagnostics.md)。

## TD3 接入还需要什么

CAN 链路层自带帧校验，但 TD3 仍需要应用层的序号、原子增益应用回读、动作租约、失联停机、故障锁存和唯一写入者。CAN 的 ACK 只说明有接收节点收到帧，不代表 PI 已应用参数。经典 CAN 单帧只有 8 字节，现有 JSON/CRC 串口帧不能直接塞进一帧；当前适配器不支持 FD，因此后续应采用版本化的经典 CAN 二进制协议或有明确时限/序号/完整性检查的分帧传输。

已新增 C 协议与控制任务接口：接收端校验并暂存完整命令，在控制周期边界应用 Kp/Ki；board callback 成功且实际 PI 回读一致后才提交应用序号；控制任务独立执行租约/失联禁能。`motor_runtime.py` 现支持 **`--transport can`**，保留现有 `Engine` 和 MATLAB 接口。Python 与编译 C 端点的 16 项软件检查通过，3 条完整回合经验通过审计；这些是软件证据，尚未在实际 FOC 固件中接入和验证。详见 [CAN 运行与协议](../skills/motor-td3-serial-tuning/references/can-runtime.md)。

后续已完成原 FOC 工程的**锁定接入副本**与完整编译，新增 16 项板级软件测试、11 项共享禁能函数/协议端点的实际 MCU RAM 测试。完整 HAL/FOC 接入固件尚未烧录运行，实机温度与保护验收、生产 boot 身份、无扰增益应用未完成，能力位保持 0；它仍不能作为 TD3 实机控制接口。见 [FOC 接入报告](stm32g431-foc-can-integration.md)。板上原 Flash 没有改变，仍是原应用。

## 公开接口依据

- [PEAK ListenOnly 参数文档](https://www.peak-system.com/documentation/API/PCAN-Basic.Net/html/3e5e1a2d-b990-4cc6-9908-001585cd3871.htm)：监听模式可在初始化前设置，并支持读回。
- [python-can PCAN 实现](https://python-can.readthedocs.io/en/stable/_modules/can/interfaces/pcan/pcan.html)：PCAN-Basic 绑定与通道能力查询。
