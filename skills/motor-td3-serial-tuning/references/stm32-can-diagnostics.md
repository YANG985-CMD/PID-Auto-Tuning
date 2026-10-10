# STM32G431 的 CAN 专用 SRAM 诊断

用于区分控制器内部问题与电脑—板端链路问题。先核对板卡 GPIO、时钟、CAN 类型及示例的实际载荷；同一个 ID 不能据此判断载荷相同。不要用包含电机启动解码的示例代替 CAN 诊断。

本包包含两种独立程序：

| 程序 | 范围与前置条件 |
|---|---|
| `scripts/can_loopback_pil.py` | 内部回环，64 个标准/扩展测试帧，GPIO 不启用；先取得电机功率电源断开的现场确认 |
| `scripts/can_echo_pil.py` | 500 kbit/s 经典 CAN，16 个固定请求/回包；需要实际板端供电、已授权的主动测试及功率输出禁能 |

两者均会暂停原应用、复位、覆盖前 20KB SRAM，检查加载镜像，运行指定 RAM 入口。结束复位暂停并比较完整 128KB Flash，不恢复原应用。仅适用于经核对的 Cortex-M4、器件 ID `0x468`、128KB Flash 目标；外部程序还限定 PA11/PA12 AF9、24 MHz HSE。不能直接用于其他板卡。

## 工具与离线构建

需要 Arm Compiler 6、pyOCD、libusb-package、pyelftools；外部收发另需 PCAN 驱动与 python-can，依赖见 `scripts/requirements-pil.txt` 和 `scripts/requirements-can.txt`。`CMSIS_ROOT` 指向含 `Include` 和 `Device/ST/STM32G4xx/Include` 的本地 CMSIS 目录；不随包分发厂商头文件。

遵循用户临时目录规范，所有 `*_OUTPUT` 为新的空任务目录。以下命令从 skill 目录执行，build 不访问硬件：

```text
python -B scripts/can_loopback_pil.py build --arm-bin ARM_COMPILER_BIN --cmsis-root CMSIS_ROOT --output LOOPBACK_BUILD_OUTPUT
python -B scripts/can_echo_pil.py build --arm-bin ARM_COMPILER_BIN --cmsis-root CMSIS_ROOT --output ECHO_BUILD_OUTPUT
```

源码为包内固定的 CAN 专用 C/汇编。构建和执行会检查 SRAM 加载范围、入口、栈、邮箱、镜像散列与模式；不接受 Flash 加载段，也不调用 Flash 编程接口。散列检查是完整性检查，不等于通用硬件安全认证。

## 内部回环

已确认功率电源物理断开，并接受复位/SRAM 替换后，在已授权会话中执行：

```text
python -B scripts/can_loopback_pil.py run --build LOOPBACK_BUILD_OUTPUT --output LOOPBACK_RUN_OUTPUT --power-stage-disconnected --reset-and-halt-ack
```

标志记录真实现场状态，不能代替现场确认。内部程序使用 16 MHz PCLK1、500 kbit/s 配置，TEST+MON+LBCK，不启用 GPIO；覆盖 64 帧、标准/扩展 ID 与 DLC 0～8。通过只说明控制器与消息 RAM 工作，不能证明板外 CAN 收发。

## 外部收发

根据实际板卡供电说明确认收发器有逻辑电源。电脑供电的 USB-CAN 与板端收发器是两个供电对象，H/L 两线不提供板端 5V。接线应按实物 H/L 与模块说明核对，断电检查终端，关闭其他通道使用者。不要给未知电源脚注入电压。

外部测试会切换 PCAN 为正常模式提供 ACK；它不是静默监听。在用户已授权主动 CAN 诊断、实际板端供电已确认的会话中，可以保留电机接线，但原应用须暂停，输出检查须通过。测试期间不按启动/复位键；不自动恢复原固件或电机运动。

```text
python -B scripts/can_echo_pil.py run --build ECHO_BUILD_OUTPUT --output ECHO_RUN_OUTPUT --channel PCAN_USBBUS1 --allow-live --board-supply-confirmed --motor-output-disabled-ack
```

运行器在支持目标暂停、复位、PWM/GPIO 初值为零、SRAM 镜像回读一致之后初始化主动 PCAN。只运行 CAN 专用入口；每个请求前检查 RAM 邮箱就绪、核心运行状态、正常 CAN 模式、比特率、TIM1 禁能及 PA8/9/10 模式。MCU 循环也检查 TIM1 时钟/寄存器与相线引脚状态。

- 固定标准请求 ID `0x6E0`、回复 ID `0x6E1`、DLC=8，载荷以 ASCII `CAN1` 开头，序号 0～15。
- 每个请求最多等待 0.3 秒；无请求重试。MCU 整体等待预算 8 秒。
- 通道占用、模式不一致、镜像/输出状态不符、错包或超时即失败，执行复位暂停和通道释放；收尾检查不通过时不得声称成功。
- 结束保持核心暂停，报告实际 PWM/Flash 状态；安排断开功率电源。若调试连接异常导致停机状态无法核对，应由现场断开功率电源，不能用主机曾发过命令代替停机证据。

不能用这些标志跳过现场供电状态或执行授权。固定诊断帧没有启停或 Kp/Ki 语义；不向已恢复的 Flash 应用发送。

## 结果判定与发布

查看 `can-result.json`。内部成功需要 64 帧、模式/数据正确、错误计数零、栈底完整；外部成功需要 MCU 收/发各 16、主机全部回包一致、正常模式/时序/输出检查正确。两者还需要最终核心暂停、PWM/GPIO 关闭、完整 Flash 未变与会话正确关闭。

区分内部回环、实际外部收发、真实应用遥测、参数实际应用、TD3 性能五种证据。CAN ACK 与诊断回包不能证明 PI 已应用增益；TD3 仍需应用序号、设备时间、一致遥测、动作租约、独立保护和固定策略对照。不得因通信通过自动转为训练或给电机下发参数。

只公开自有程序与脱敏摘要，私有 Flash 内容仅在内存中比较。本次 2026-10-10 实测：内部 64/64、外部 16/16；TIM1 关闭、Flash 未变。电压精度与生产 FOC 的通信/实时预算需在正式接入后另测。
