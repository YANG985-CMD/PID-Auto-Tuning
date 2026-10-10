---
name: motor-td3-serial-tuning
description: "Build or run a Codex-managed motor serial/CAN-to-MATLAB TD3 workflow for bounded speed-loop PI gain schedules. Use for training, experience audits, fixed-policy evaluation, Actor C export/RAM PIL, STM32G431 CAN diagnostics, and locked FOC integration."
---

# Motor TD3 Serial Tuning

把用户的串口调参流程扩展为：本地串口或 CAN 监督器采集电机响应，TD3 程序训练参数策略，Codex 配置、启动和检查结果。默认调速度环 `Kp、Ki`；保留现有电流环、FOC 和硬件保护。用户明确指定其他控制结构时重新定义接口。

## 职责与边界

- Codex 读取摘要和必要的数据片段，管理实验与代码；神经网络由本地训练程序更新。高频原始串口数据保存在本地，不逐帧输入聊天模型。
- 串口只由一个持续运行的监督器占用。训练、预测、界面通过进程间队列访问它；VOFA 先断开同一端口。
- 采样、检查故障、停止输出和租约看门狗独立于梯度计算。主机被暂停或进程终止时，设备仍须自行进入经验证的安全状态。
- Skill 安装、生成代码、检查数据不表示已经授权电机转动。根据会话中现有授权判断；未授权的真实参数下发、启动和探索需要用户授权。已有明确授权不重复询问。
- 一般串口曲线不等于 TD3 训练数据。必须能把状态、实际生效的动作、随后响应和奖励对应起来。
- 参数范围、慢速更新和奖励惩罚均不能证明闭环稳定；保护门槛来自该电机、驱动器和机械负载的工程验证，不能由 AI 猜一个“安全值”。

## 选择工作模式

| 用户目标 | 执行方式 |
|---|---|
| 设计流程或检查现有固件 | 离线检查，不打开串口 |
| 采集串口数据 | 校验端口与协议，只读采集；注意打开串口可能改变 DTR/RTS 或复位板子 |
| 看网络会怎么调参数 | `shadow`：预测并记录，与实际动作区分，不下发预测参数 |
| 训练第一版策略 | 优先仿真预训练；用户明确选择实机时可做监督下的受限在线 TD3 |
| 用已有日志训练 | 先审计动作覆盖和时序；普通 TD3 的离策略能力不等于可靠的纯离线学习 |
| 上板在线调参 | 通过下述实机门槛，运行限时会话；训练与采集解耦 |
| 评估或部署 | 固定网络版本，关闭探索，按独立测试工况比较现有控制器 |
| 在 G431/G441 上验证 Actor 计算 | 断开功率电源后，用 RAM PIL 比较 MCU 与 MATLAB；不应用增益、不写 Flash，结束保持暂停 |
| 诊断 G431 的 CAN 链路 | 按 [stm32-can-diagnostics.md](references/stm32-can-diagnostics.md) 选择内部回环或有界 PCAN 收发；运行专用 SRAM 程序并检查 PWM 禁能 |
| 验证 G431 独立看门狗 | 按 [g431-watchdog.md](references/g431-watchdog.md) 在功率物理断开时运行 RAM 复位诊断；SpeedLoop 禁止运动集成及真实心跳停止按 [speedloop-watchdog.md](references/speedloop-watchdog.md)；不等于运动停机验收 |
| 没有温度传感器，设计热保护 | 按 [sensorless-thermal.md](references/sensorless-thermal.md) 完成 MCU 三相热预算的离线检查；先标定电流并取得过载/功率板依据，软件通过不批准实机 |
| 验证 G431 比较器到 Break 的信号路径 | 按 [g431-comp-break.md](references/g431-comp-break.md) 在功率电源物理断开时运行 SRAM DAC 阈值诊断；它不校准电流，也不测量功率输出关闭延迟 |
| 观察 G431 三相电流 ADC 零点 | 按 [g431-current-zero.md](references/g431-current-zero.md) 在功率电源物理断开时运行 SRAM ADC 观察；它不写偏置、不校准增益，也不批准过流门槛 |
| 用已知电流拟合 ADC 增益 | 按 [current-calibration.md](references/current-calibration.md) 准备同步参考电流/ADC 数据并运行离线拟合；没有已知电流源时不得估算或写入保护参数 |
| 把 CAN 数据接入 TD3 | 按 [can-runtime.md](references/can-runtime.md) 接入 C 协议和板级 hooks，通过现有实机门槛后使用 `--transport can` |

每次先确定“每个试验选择一组固定参数”还是“运行中多次调整参数”。后一种才是此 skill 默认的动态参数策略；不要把单步参数搜索的结果描述为已学会运行中的自适应控制。

本包运行器目前支持 mock、`train-live` 和 `evaluate`；只读采集/旁路预测是工作模式建议，执行前需补相应入口，不要声称已有命令。

## 工作流程

1. 检查工程说明和相关源文件，定位参数写入点、PI 积分实现、速度/电流任务周期、串口协议和独立停机机制。按需读 [project-map.md](references/project-map.md) 建立目标工程的接入点映射。
2. 从 [session-profile.example.json](assets/session-profile.example.json) 建立会话配置。示例里的 `null` 表示必须从工程或用户取得的信息，禁止直接用于实机。参数初值是源代码默认值，未被认定为当前设备的安全基准。
3. 运行本包程序时读 [matlab-runtime.md](references/matlab-runtime.md)：使用 `scripts/run_mock.py --output TASK_TEMP_DIR` 复现桥接、真实 MATLAB TD3 更新、评估和 C 导出；实机使用 `scripts/motor_runtime.py` 与 `matlab/trainMotorTD3.m`。按 [architecture-and-training.md](references/architecture-and-training.md) 检查状态、动作、奖励与时序。不要让聊天模型代替反向传播。
4. 按 [serial-and-safety.md](references/serial-and-safety.md) 检查固件、协议和保护。先完成 mock、错误注入和只读检查。使用 `scripts/session_checks.py check-profile CONFIG --live` 检查配置完整性；脚本通过只表示配置齐全，不能替代设备验证或本次授权。
5. 使用 `scripts/session_checks.py audit-transitions LOG --profile CONFIG` 检查实际用于学习的 JSONL 数据。脚本不打开串口、不下发命令、也不训练网络；详细格式在安全参考中。
6. 实机允许后，先用已验证基准完成有界试验，再在已验证局部参数范围内逐步探索。禁止沿用库的全范围随机动作默认值。限制单轮时间、动作次数和累计通电预算；不因训练分数较低自动放宽限制。
7. 每次策略更新先形成候选检查点。当前实现每轮确认停机后做梯度更新；实机候选不会自动替换基准行为。通过 `--approved-policy` 明确选定已有候选后，使用 `matlab/evaluateCheckpoint.m` 评估，验证输入尺度和输出映射；恶化时回退到已验证控制器。严重故障先停机，禁止自动重启。
8. 用未参与训练的工况比较固定 PI、现有模糊 PI 和 TD3。交付原始数据、实际生效参数、故障和拒绝记录、检查点、归一化配置、测试结果及尚未验证的部分。
9. 用户授权试板或部署时，先核对板卡资料和芯片身份。按 [stm32-ram-pil.md](references/stm32-ram-pil.md) 可在 G431/G441 128KB 目标上运行计算专用 RAM PIL。它会复位、覆盖 SRAM、保留 Flash、保持核心暂停；必须先取得功率电源物理断开的确认。RAM 推理通过不表示策略可用于电机闭环，也不表示已烧录到 Flash。不要结束后自动恢复原应用或接通功率电源。

CAN 通信问题单独按 [stm32-can-diagnostics.md](references/stm32-can-diagnostics.md) 处理：先辨别示例载荷与当前固件，不用含电机启停的示例代替通信诊断。专用外部收发诊断允许在明确授权、板端供电已确认、功率输出禁能的条件下运行；每次发送前核对 SRAM 就绪状态及 PWM/引脚状态。CAN 回包通过只验证通信，不解除实机训练门槛。

CAN 训练接入读 [can-runtime.md](references/can-runtime.md)。已有 PCAN 主机入口和可编译 C 端点，软件完整回合已验证；G431 原 FOC 工程的锁定接入副本已完整编译，具体按 [g431-locked-integration.md](references/g431-locked-integration.md) 操作。其能力为 0，禁止启动/增益应用；共享禁能函数与协议端点的真实 RAM 测试通过，完整 FOC 接入固件尚未烧录执行。缺失温度保留 NaN，不伪造训练观测。使用 `can-session-profile.example.json` 配置，不复制软件测试 peer 的验证标记到真实配置。

检查温度及参数限制时，先核对应用实际采样通道、板卡原理图和具体示例版本。没有温度传感器时记录能力缺失，再设计测温或经验证的替代热保护；按 [sensorless-thermal.md](references/sensorless-thermal.md) 使用离线 MCU 热预算及 ADC 接入层。禁止运动的 SpeedLoop 热审计副本已完成链接检查，缺少校准记录时拒绝启动，尚未烧录。热预算日志按 [thermal-can.md](references/thermal-can.md) 用 `scripts/thermal_can.py` 离线解析；`0x626` 是独立诊断，要求准确零能力 HELLO 身份，未知数值保留 null，解析通过不批准启动或生成训练经验。当前运行器仍显式拒绝替代模式，训练协议与实机运动接入未完成。预算不是摄氏温度；STOP/新回合保留预算，未知启动热状态拒绝运行。模糊规则的可达增益集合、Iq 指令限幅和 DAC 码值不是已验证的实机安全域。

用户指定 `17.SpeedLoop` 时按 [speedloop-diagnostic.md](references/speedloop-diagnostic.md) 创建禁止运动的 GNU Arm 诊断副本，不复用 PID/NNSMC 的状态字段。该版本取消 TIM1/CH4 启动，使用约 100Hz 软件 ADC 诊断；不是 10kHz FOC 或训练遥测。原 CH4 触发依赖 MOE；调试器暂停也不会自动关闭 PWM。允许运动前应先禁能再确认停机，不能把 halt 当急停或把逐个 HAL Start 声称为原子输出使能。

SpeedLoop 已有 `scripts/speedloop_can_capture.py`：完整镜像/禁能状态核验后只发一次 HELLO，限时采集原始诊断；身份或顺序异常立即拒绝，不重试。结束先暂停已核验的禁止运动固件、确认输出关闭，再释放 PCAN，避免残留发送失去 ACK。它不启动、应用增益或生成训练经验。下载前必须在功率物理断开时 reset halt，确认 SysTick/外设复位，不能只接到已暂停的应用就擦写 Flash。

独立看门狗按 [g431-watchdog.md](references/g431-watchdog.md) 处理。专用 RAM guest 已验证停止前台喂狗、关闭可屏蔽中断两种 IWDG 复位，并保持 Flash 未变；`motor_td3_health` 监督器只在前台处理一致快照，要求主循环/时钟/ADC 新进展和有效心跳期限，故障锁存。它已接入禁止运动 SpeedLoop 副本，三种断电故障与真实 CAN 应用心跳停止均产生 IWDG 复位，复位后保持禁止启动。按 [speedloop-watchdog.md](references/speedloop-watchdog.md) 构建/核验固定镜像并使用专用入口；CAN 只发 HELLO/STOP，心跳撤回期间保留 ACK，故障不自动重装会话。重新烧录、复位或 prepare 须功率物理断开；run 须现场板端供电确认。约 200ms 诊断超时不作为运动保护阈值。

## 实机门槛

实机训练或策略下发前，必须有该设备的：已验证基准；带来源的参数/电流/转速/电压/温度和持续时间限制；实际参数回读及应用序号；固件独立过流保护与失联保护；经过验证的停止动作和急停；有期限的动作租约；可追溯的协议版本、固件版本和实验日志。

其中任何关键项缺失时，继续离线设计、代码修改和 mock 验证，说明具体缺口。用户若仅要求制作或安装 skill，不执行实机试验。

参数回退需要与停机区别处理：正常性能恶化可按验证过的无扰切换策略回到基准；过流、传感器无效、通信故障等情况先进入硬件安全状态。设备失联时不把“主机发送过 STOP”当成停机成功。

## 文件与验证

- 遵循用户或项目指定的临时目录规范；未指定时使用系统临时目录下的独立任务目录，避免在源文件目录生成临时日志、试验检查点或测试输出。用户要求保留的正式数据和最终模型放在指定交付位置。
- Python 检查使用 `-B` 或 `PYTHONDONTWRITEBYTECODE=1`，避免在 skill 或用户工程里生成缓存。
- `scripts/session_checks.py self-test` 在内存中验证缺失边界、NaN、时序错配、确认缺失、终止类型和回合串接等问题，无硬件副作用。
- 本包包含持久桥接器、MATLAB TD3 训练/评估、Actor C 导出与主机数值检查、MCU 协议/保护参考模块和 mock 故障测试。实际板级接入按 [firmware-integration.md](references/firmware-integration.md) 完成；不能把 mock 或主机测试说成硬件保护/上板验证。
- 分析结果时明确指出经验审计、训练更新、独立性能比较和目标计算验证各自的结论。即使权重更新和 PIL 通过，候选性能没有改善或保护未验证时，不发布为实机闭环策略；记录具体原因。
- 使用 `scripts/test_runtime.py --output TASK_TEMP_DIR` 与 `scripts/test_firmware.py --output OTHER_TASK_TEMP_DIR --compiler GCC` 验证故障路径；输出不放用户源工程。实机配置不完整时继续这些独立工作。
