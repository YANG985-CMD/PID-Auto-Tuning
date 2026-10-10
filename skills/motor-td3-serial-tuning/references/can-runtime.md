# CAN 接入 MATLAB TD3

读取此文件处理 `--transport can`、CAN 固件接入和经验归因。物理链路已通过独立 SRAM 诊断；本节的训练协议是新增应用层，已经通过 Python 与编译 C 的软件测试及 Cortex-M4F 对象编译，尚未在原 FOC 固件中完成板级接入或实机保护验证。

## 文件与主机入口

- `scripts/can_transport.py`：二进制协议、分帧/重组、CRC 和独占 PCAN 正常模式。
- `scripts/motor_runtime.py` 的 `CanDevice`：持续采集、握手、实际参数确认、响应窗口和 STOP 回读；复用串口的经验审计与 MATLAB TCP 接口。
- `firmware/motor_td3_can.c/.h`：固定内存 C 协议。
- `firmware/motor_td3_can_control.c/.h`：单槽命令、控制周期应用、实际 PI/PWM 回读和独立 guard。
- `scripts/test_can_runtime.py` 与 `firmware/tests/can_test_peer.c`：无硬件软件端点，不包含 HAL 或真实电机。

从 skill 目录运行无硬件验证，使用指定临时根目录下新的输出目录：

```text
python -B scripts/test_can_runtime.py --output TEST_OUTPUT --compiler GCC_EXECUTABLE
```

从 `assets/can-session-profile.example.json` 建立实际配置。模板为 plan 模式，缺少现场验证的项目保留 null/false。只有板级接入和独立保护验证已完成、且会话已有实际运动授权时，才能运行：

```text
python -B scripts/session_checks.py check-profile CAN_PROFILE --live
python -B scripts/motor_runtime.py --profile CAN_PROFILE --output RUN_OUTPUT --token-file TOKEN_FILE --transport can --allow-live
```

PCAN 驱动、python-can 依赖同 `scripts/requirements-can.txt`。只支持经典 PCAN USB、500 kbit/s，不支持 CAN-FD。占用中的通道拒绝打开；设置并持续核验正常模式，不共享写入者，不调用适配器 Reset。协议验证、参数边界和保护证据没有齐全时，在打开驱动前拒绝运行。

MATLAB 的 `trainMotorTD3`、`evaluateCheckpoint` 与本机认证 TCP 接口保持相同。Codex 负责检查配置、启动程序、分析经验与固定策略评估；梯度更新由 MATLAB 执行。不得把软件端点的验证配置用于实际板子。

## 固定线协议 v1

使用标准请求 ID `0x620`、回复 ID `0x621`，每帧 DLC=8；均不同于诊断 ID 和厂商扩展 ID `0x1B`。只处理经典标准数据帧，不接收 RTR、FD/BRS 或错误状态帧作为数据。

| CAN 帧字节 | 内容 |
|---|---|
| 0 | 固定 `0xD1` |
| 1 | uint8 传输计数，可回绕；仅用于分帧归属 |
| 2 | 分片索引，从 0 开始，连续递增 |
| 3 | 数据包总长度，36～192 字节 |
| 4～7 | 数据包的 4 个字节；最后不足部分为零 |

从首片开始 50ms 内必须收到完整包。重复片、缺片、重排、重叠包、长度改变、非零填充、时钟倒退、CRC 错误都失败。C 端 RX 只排队；控制任务独立处理分片超时和故障禁能。不要自动重试动作或把不完整命令续租。

完整包全部小端，header 为 32 字节，末尾为 IEEE CRC32 的 uint32，覆盖前面所有字节：

| 包偏移 | 类型与字段 |
|---|---|
| 0 | uint8 version=1 |
| 1 | uint8 kind：hello=1、begin=2、gains=3、stop=4、hello_reply=0x81、telemetry=0x82 |
| 2 | uint16 reserved=0 |
| 4 | uint64 host nonce，非零 |
| 12 | uint64 boot ID；每次 MCU 重启必须改变 |
| 20 | uint32 wire_seq；命令从 1 连续递增，遥测使用自己的连续序号 |
| 24 | uint64 expires_us；设备单调时间上的绝对有效期 |
| 32 | 类型对应的 payload |

hello 请求的 boot/seq/expires 均为 0，payload 为 `uint8 length + ASCII profile`。回复 seq/expires 为 0，payload 为 `uint16 capabilities + firmware string + profile string`。标识符为 1～64 个 ASCII 字母、数字、`-_.`；每个字符串带 uint8 长度。六个 capability 位依次为 atomic_gains、applied_feedback、lease、link_watchdog、fault_latch、single_owner；板级功能实际验证前不得声明对应位。

begin payload 为 `float32 speed_ref + uint32 lease_ms`；给定必须在固件保存的已验证计划内。gains payload 为 `uint32 command_seq + float32 kp + float32 ki + uint32 lease_ms`，一起原子应用。stop 无 payload，不受动作有效期限制，不能续租或清故障。

telemetry payload 为 `uint64 t_us, uint64 t_apply_us, uint32 applied_seq, uint32 fault, uint8 enabled, 3 bytes zero, 10 float32`；浮点顺序为 `speed_ref, speed, error_history, integral_output, current, vbus, temperature_c, kp, ki, elapsed_ms`。完整遥测包 104 字节，即 26 帧。主机把 boot 转为 16 位十六进制字符串，状态、单位和经验格式与已有运行器相同。

主机从最新已通过检查的设备时间加 `max_apply_latency_ms` 生成有效期；MCU 检查命令已过期或有效期远超本次最大应用时限。nonce、boot、连续 wire_seq 共同拒绝旧启动、旧会话及重放；它们不是密码学身份认证，v1 面向受控的本地实验总线。

## 控制任务和板级 hooks

调用 `motor_td3_can_control_init` 时必须提供实际板级 hooks、已验证 limits/ref 计划、非零且每次重启变化的 boot、最大命令时效与真实 capabilities。参考函数不包含某块板的 GPIO/PWM 初始化或下载配置。init 先调用禁能 hook；失败时不能继续运行服务。

| hook | 板级义务 |
|---|---|
| disable | 实际关闭驱动/PWM，并阻止其他启动路径重新使能 |
| begin | 检查允许状态、建立可重复初态和基准参数、按已验证方式启动；只有成功才返回 1 |
| apply | 同一控制周期边界更新两个实际 PI 参数，保持已验证的无扰切换和抗饱和；只有成功才返回 1 |
| snapshot | 提供一致的真实控制状态；Kp/Ki 来自控制器实际存储，enabled 来自实际功率输出状态 |

RX 接收只在独占请求 ID 上重组并写单槽 pending，不写 PI。RX 与控制任务访问 pending 时由板级调度保证互斥；ISR 不调用启动/禁能 hook。队列占用/溢出或 CAN 驱动、FIFO、bus-off 错误应设置 `rx_fault`，随后由独立高优先级控制周期禁能。

每个控制周期调用 `motor_td3_can_control_tick(ctx, now_us, estop_or_sensor_invalid)`，不得依赖主机收到数据才调用。它先执行 guard，再检查会话、命令时效和序号；增益先作用于临时候选 guard，board apply 成功且实际回读一致后才提交应用序号和时间。callback 失败、假成功但参数未变、物理输出与 guard 不一致都锁存故障。

hello、残缺包和无效命令不续租。STOP 与故障实际调用 disable，应用序号跨普通停机保持单调。每个 boot 只接受一次 owner 握手；重新建会话须遵循板卡的已验证重启/重臂流程，禁止主机自动复位或清故障。

用 `motor_td3_can_make_hello` / `motor_td3_can_make_telemetry` 建立完整快照后，以 `motor_td3_can_fragment` 分帧放入非阻塞发送队列。不要在电流中断阻塞发送；队列必须保证同一数据包字节在发送结束前不被覆写。普通包体、标识、命令序号和设备时间溢出前结束会话。

104 字节遥测需 26 帧，以每帧约 135 位作保守预算，20ms 周期约占 500 kbit/s 的 35.1%，还需为命令、回复、重传和其他总线负载留空间。运行器要求 `telemetry_period_ms >= 20`、不大于 `max_frame_gap_ms`，且应用时限大于分片时限加遥测周期。实际总线占用、队列容量和实时延迟必须在板上测量；该预算不是可靠性证明。

## 此次目标工程映射与待验证项

本地 `17.PID control speed` 中，速度参数位于 `spd_kpki.spd_kp/spd_ki`，积分状态为 `rtDW.Integrator_DSTATE_h/Integrator_PREV_U`，源代码积分含 `0.001 × speedloop_ELAPS_T`，属于连续 Ki。原 USER3 路径能直接改变 PWM，接入 AI 模式必须限制它与其他增益写入路径；急停须保留并独立有效。

当前源代码还包含 NNSMC 的 RBF 滑模补偿叠加在原 PI 上。实机基准与候选须使用一致的实际控制结构；不能用 mock 的纯 PI 结果推断这个实际控制器的收益，也不能未经验证删除补偿。源文件与历史构建固件的版本对应需在正式构建时重新核对。

仍须接入板级 FDCAN RX/TX、64 位计时、上述 hooks、Hall/电流有效性与热保护，并进行禁能、断流/主机终止、无扰更新和唯一参数写入者的实际验证。软件测试中的 24V、30℃和反馈值是明确的测试数据，不是实际板子测量。
