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

这给出了此前零帧记录的一个待验证原因，而不是已确认的故障。保持 24V 功率电源断开，先在实物标有 5V 的测试点/排针相对 GND 测电压；不要根据原理图编号猜测实物测试点，不直接给未知电源脚注入 5V，也不通过重新接通电机母线来跳过检查。还应区分 MCU 当前暂停、收发器无电、ACK 缺失、比特率和接线等原因。

## 当前状态

对应板上 Flash 的 `17.PID control speed` 工程已经包含 FDCAN。2026-10-10 再次通过 STLink 只读比较，Intel HEX 的全部 33,500 字节程序记录与板上 Flash 一致。本次没有烧录。

- `fdcan.c`：经典 CAN、500 kbit/s、正常模式、关闭自动重发，GPIO 使用 PA12/TX 和 PA11/RX。
- `main.c`：调用 `MX_FDCAN1_Init()`、`FDCAN_Config()`，约每 10 ms 尝试发送扩展 ID `0x1B`、DLC=8 的帧。
- `TxData[8]`：初始化为零，工程没有把速度、电流或母线测量写入该缓冲区，故它是占位载荷，不能解释成有效电机遥测。
- `stm32g4xx_it.c`：接收数据存入 `RxData`，没有 TD3 增益、停止命令、序号应用确认或租约处理。
- UART3 的 24 字节 Hall 遥测仍是另一路数据，布局见 [legacy-board-telemetry.md](legacy-board-telemetry.md)。

因此，先前“原固件没有启用 FDCAN”的说法已更正为：**已初始化 CAN，但没有实现 TD3 协议**。源码的 PA12/TX 与新版原理图的 PB9/TX 不同；实物排针布局现已与较旧资料核对相符，但完整 PCB 版本及内部 GPIO 走线尚未独立确认。

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
4. 验证收发器逻辑电源也有电。USB/STLink 能给 MCU 供电，不证明 CAN 收发器的 5 V 电源已存在；禁止因此自动接通电机母线。
5. 先使用 500 kbit/s 静默监听。Listen-Only 不提供 ACK；总线只有 MCU 和这个监听器时，发送可能不获应答。零帧或 ACK 错误不能单独证明接线坏，也不能当作双向通信通过。后续正常收发测试应在独立保护和电源条件核对后另行进行。

## 2026-10-10 本次验证

公开的结构化结果见 [验证摘要](../examples/stm32g431-can/summary.json)；未上传原始私有工程、Flash 内容或设备序列号。

- PCAN 驱动能力查询成功：PCAN-USB、经典 CAN、通道可用。
- 初始化前和初始化后的 Listen-Only 都读回为开启；500 kbit/s 监听约 5.14 秒，收到 0 帧，随后释放适配器。
- 9 项无硬件故障测试通过，包括模式设置失败、通道占用、错误比特率、模式被更改、接收错误和关闭清理。
- 本次未发送 CAN 控制命令、未恢复 MCU 运行、未写 Flash。重新核对 MCU 时发现它已处于运行状态，原固件 `Motor_state=255` 且功率输出使能；无法确定谁或什么使其恢复。Codex 随即暂停、复位并核对 `CR1/CCER/BDTR=0`，结束保持核心暂停。用户确认 24 V 已断开。
- 后续照片已确认板端 H/L 丝印及 8 针排针布局，并识别到配套欧拉 USBCAN / PCAN 模块。MCU 只读复查仍为暂停，TIM1 的 CR1/CCER/BDTR 均为 0。
- 目前没有完成板端 CAN 帧收发验证；完整 PCB 版本、收发器逻辑供电、导线连续性和应用协议仍未验证。禁止把 0 帧记录解释为电机控制通信成功。

## TD3 接入还需要什么

CAN 链路层自带帧校验，但 TD3 仍需要应用层的序号、原子增益应用回读、动作租约、失联停机、故障锁存和唯一写入者。CAN 的 ACK 只说明有接收节点收到帧，不代表 PI 已应用参数。经典 CAN 单帧只有 8 字节，现有 JSON/CRC 串口帧不能直接塞进一帧；当前适配器不支持 FD，因此后续应采用版本化的经典 CAN 二进制协议或有明确时限/序号/完整性检查的分帧传输。

改造位置已明确：在 FDCAN 接收端校验并暂存完整命令，在控制周期边界一次应用 Kp/Ki；把真实参数、应用序号、设备时间、速度、电流、母线和故障写入一致遥测快照；控制任务独立执行租约/失联禁能。训练器的 `Engine` 和 MATLAB 接口可以保留，但当前 `motor_runtime.py` 仍只支持 mock/serial，**没有 `--transport can` 训练入口**。

在没有完成上述固件改造、编译和断电验证前，CAN 只能作为物理通信通道，不能作为 TD3 实机控制接口。Codex 可以先监听并分析帧，再在协议固定后把 MATLAB/桥接器的传输层接到 CAN。

## 公开接口依据

- [PEAK ListenOnly 参数文档](https://www.peak-system.com/documentation/API/PCAN-Basic.Net/html/3e5e1a2d-b990-4cc6-9908-001585cd3871.htm)：监听模式可在初始化前设置，并支持读回。
- [python-can PCAN 实现](https://python-can.readthedocs.io/en/stable/_modules/can/interfaces/pcan/pcan.html)：PCAN-Basic 绑定与通道能力查询。
