# STM32G431 CAN 实测与原因分析

日期：2026-10-10。Codex 先检查本地 CAN 示例和板卡资料，再编写独立 SRAM 诊断程序，经 STLink 加载并读取结果。公开记录不包含厂商源工程、原理图、私人照片、设备序列号或 Flash 内容。

## 参考示例给出的信息

| 本地工程 | CAN 配置与载荷 | 对本次测试的影响 |
|---|---|---|
| `8.CAN / STM32_GPIO` | PA11/RX、PA12/TX，AF9，500 kbit/s；扩展 ID `0x1B`，前 4 字节为小端 float 母线电压，后 4 字节为零 | 确认 GPIO、24 MHz HSE 和时序来源；不能把其他工程的相同 ID 都按电压解析 |
| `4.BLDC_hallsensor_CAN` | 同一 GPIO 和比特率；发送模式、方向和速度；接收首字节 `0x01` 的命令可按第 5 字节启停电机 | 存在真实启动路径，不能直接运行整个示例来做通信检查 |
| 板上 `17.PID control speed` | 扩展 ID `0x1B`、8 字节全零占位载荷；没有 TD3 参数应用序号、租约和增益回读 | 原固件已初始化 CAN，但不能把占位帧当成 TD3 经验 |

套件 V13.1 手册的 PDF 第 92 页 CAN 实验接线图同时画出了电脑 USB 接口和开发板的 24V/3A 电源。电脑 USB 为适配器供电；仅连接 H/L 不会给开发板收发器供电。对应排针布局的原理图中，收发器接板上 5V 电源链。本次没有取得万用表的 5V 测值，不能把功能测试写成电压测量。

## 1. 内部回环：64/64 通过

在用户已确认 24V 断开的状态下执行内部回环。CAN 使用复位后的 16 MHz 内核时钟，配置 TEST、MON 和 LBCK；不初始化 GPIO。内部回环验证控制器与消息 RAM，不验证板外收发器、H/L 接线和适配器。

- 标准帧 32 个、扩展帧 32 个，覆盖 DLC 0～8，每个有效载荷字节均比较。
- 全部 64 个完成，ECR 为零；内部时序配置对应 500 kbit/s。
- 镜像 1,912B；栈最大观测占用 64B，栈底检查通过。
- TIM1 CR1、CCER、BDTR 及 GPIO 时钟均为零；结束核心暂停，完整 128KB Flash 未变。

最初的诊断错误来自标准帧 ID 的比较掩码。标准 ID 位于接收头的 bits 28:18，不能把低 18 位也当成标准 ID 比较；改用 `0x1FFC0000` 后全部通过。这是 Codex 对诊断软件的修正，不能归因于硬件故障。[ST G4 HAL 的接收头解析](https://github.com/STMicroelectronics/stm32g4xx-hal-driver/blob/master/Src/stm32g4xx_hal_fdcan.c)采用相同的标准 ID 位域。[ST 内部回环说明](https://www.st.com/content/st_com/en/technical-documents/an5348-introduction-to-fdcan-peripherals-for-stm32-mcus-stmicroelectronics_asset/chunk-002-topic-an5348-implementation-can-fd.html)解释了回环与外部总线之间的区别。

[机器可读结果](../examples/stm32g431-can-loopback/summary.json)

## 2. 电脑与板端收发：16/16 通过

用户明确要求保留电机接线，并确认开发板 24V/3A 已接。Codex 运行 CAN 专用 SRAM 程序：没有 FOC 初始化、TIM1 初始化、电机启动函数或增益下发。仅 PA11/PA12 配置为 CAN；PA8/9/10 保持复位的模拟模式，GPIOB 时钟关闭。

| 项目 | 实测结果 |
|---|---|
| 适配器 | PCAN-USB，经典 CAN，正常模式，可提供 ACK |
| CAN 时钟与比特率 | HSE 标称 24 MHz；prescaler=3，seg1=10，seg2=5，500 kbit/s |
| 报文 | 标准 ID `0x6E0` 请求、`0x6E1` 回包，8 字节 |
| 固定载荷 | `43 41 4E 31 n (n XOR FF) (n XOR A5) 5A`，n=0～15 |
| 主机比较 | 16 个回包的 ID、长度、序号及全部字节一致 |
| MCU 计数 | 收到 16 个请求、完成发送 16 个回复，error=0、ECR=0 |
| 程序 | 1,756B SRAM 镜像，栈底检查通过 |
| 输出检查 | 每次主机发送前及 MCU 循环内检查 PWM 禁能；最终 CR1/CCER/BDTR=0 |
| 收尾 | 核心暂停、GPIO 时钟关闭、128KB Flash 未变、PCAN 通道释放 |

测试后用户确认 24V 已断开，Codex 随后通过 STLink 只读复查：核心仍为 HALTED，TIM1 CR1/CCER/BDTR 及 GPIO 时钟均为零；该复查没有复位或写入内存。原 Flash 应用保持暂停。软件诊断检查通过不能替代生产固件的独立硬件保护。

这证明本次条件下电脑适配器、板端 CAN 控制器、PA11/PA12 路径及外部收发链路可以双向通信；并未测定终端电阻值、5V 精度或所有工况的通信可靠性。

[机器可读结果](../examples/stm32g431-can-echo/summary.json) · [可复用程序和命令](../skills/motor-td3-serial-tuning/references/stm32-can-diagnostics.md)

## 此前为什么监听不到帧

此前的静默监听收到 0 帧，当时 MCU 后续检查为暂停，板端收发器 5V 没有测量，监听节点也不提供 ACK。该记录不能区分这些原因。现在在板端供电已确认、专用程序运行、PCAN 正常模式的明确条件下，双向测试通过；没有证据认定之前一定是接线坏或收发器坏。

Codex 的作用是查阅示例与接线资料、构建受限诊断、检查目标身份和输出状态、分析回包与寄存器，并将实际证据记录下来。MATLAB 继续承担 TD3 训练；此前 Actor RAM PIL 已验证 MCU 可以执行网络推理。

## 下一步与当前范围

CAN 物理链路已验证，TD3 实机通信接口仍需版本化二进制协议、原子 Kp/Ki 应用与序号回读、一致遥测、动作租约和独立失联禁能。当前训练桥接器仅支持 mock/serial，没有 CAN 训练入口。

本次没有训练真实电机、应用 TD3 增益、启动电机或擦写 Flash。独立通信测试通过后，应按 [CAN 接入说明](stm32g4-can-path.md) 接入并验证这些应用层要求。
