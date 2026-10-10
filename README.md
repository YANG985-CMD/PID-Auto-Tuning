# Codex 电机 TD3 训练、结果分析与 MCU 部署

把电机串口数据送进 MATLAB 训练 TD3，输出有界的速度环 Kp、Ki，经串口应用确认后形成学习经验；Codex 管理实验和分析结果，最终导出仅用于推理的 Actor C 代码。

**Codex 可以管理 TD3 训练、分析训练结果，并将 Actor 部署到单片机执行。** 本项目已跑通真实 MATLAB TD3 训练与独立评估，并在实际 **STM32G431** 上完成 Actor 的 **RAM 部署及推理验证（PIL）**：40 组测试通过，原 Flash 内容保持不变。电机闭环训练和永久 Flash 部署仍待验证。

## Codex 在这里做什么

| 工作 | Codex 的具体作用 | 本项目证据 |
|---|---|---|
| 管理训练 | 检查接口、配置实验、启动串口桥接与 MATLAB；MATLAB 执行 TD3 梯度更新 | [20 轮真实 TD3 更新](examples/mock-validation/training-summary.json) |
| 审计训练数据 | 检查实际生效的参数、动作序号、时间和下一状态能否对应 | [780 条经验审计](examples/mock-validation/experience-audit.json) |
| **分析训练好坏** | 比较固定 PI 与固定 TD3 的误差、超调、电流、饱和和故障；解释候选是否值得使用 | [独立评估](examples/mock-validation/evaluation-summary.json)：改进 TD3 在 mock 工况优于 PI，但仍未批准电机闭环部署 |
| **部署到单片机** | 导出 Actor C、目标编译、核对芯片、加载到 MCU RAM、读取并分析推理结果 | [G431 板上验证](docs/stm32g431-validation.md)：40 组通过，Kp/Ki 与 MATLAB 一致 |
| 管理正式上线 | 接入真实观测与保护，构建/烧录目标固件，检查输入尺度、性能和实时预算 | 提供接入流程；本次尚未完成电机闭环与永久 Flash 部署 |

例如，Codex 的本次分析结论是：**原始训练的误差没有改善，原因是探索没有覆盖高增益区域；加入有界方向性覆盖、增加训练更新并把峰值电流/过冲/饱和写入奖励后，mock 三个工况的平均误差下降约 2.78%。网络可以上板计算，是否适合接管真实电机仍需单独验证。**

## 工作链路

![电机串口与 MATLAB TD3 工作流程：MCU 独立控制与保护、Codex 管理的桥接程序、MATLAB 训练与预测、实验日志及结果分析](docs/images/motor-td3-workflow.png)

<details>
<summary>查看文字版流程</summary>

```text
MCU：FOC + 速度 PI + 独立保护
           ⇅ 串口 CRC 帧、原子增益命令、实际应用反馈
Python：持续采集、安全监控、动作租约、单一端口所有者
           ⇅ 认证的本机 TCP
MATLAB：Actor 推理 → 有界试验 → 确认停机 → TD3 更新
           ↓
固定策略评估 → Actor JSON → C99 推理 → 目标工程接入/PIL

Codex：配置、启动、读取日志摘要、比较训练结果、管理部署。
```

</details>

聊天响应不会承担实时电机控制。梯度更新在每轮停机后进行；同一轮内网络仍能多次调整参数。新训练的实机候选不会自动接管电机。

## 使用声明

> [!IMPORTANT]
> 本项目用于电机控制研究、仿真和经过验证的受限实验。公开结果包含模拟训练、主机测试，以及断开功率电源后的 STM32G431 RAM 推理验证。尚未完成真实电机闭环训练和正式固件部署验收，不构成实机安全、闭环稳定性或调参性能保证。

- **示例仅供演示：**模拟配置、PI 参数和示例网络不能直接用于真实电机；改进 TD3 的优势只在 mock 工况得到验证。
- **实机使用须先验证：**针对目标电机、驱动器和负载确认基准、参数边界、变化步长及电流/转速/电压/温度/持续时间限制，并验证原子参数更新、实际应用回读、独立过流、急停、失联保护和动作租约。
- **实验须明确授权并限制范围：**实机试验在已授权的工况、时间和动作预算内进行；发生故障先执行经验证的停机路径，禁止自动清故障或重启。
- **实时保护由 MCU 执行：**Codex 管理本地桥接和训练程序，不能代替 MCU 的实时闭环、独立保护或现场急停。
- **部署以独立验证为依据：**候选网络须与已验证控制器进行独立比较，并完成目标编译、内存/执行时间检查及 SIL/PIL；本次 RAM PIL 仅验证计算，不批准模拟网络控制真实电机。

## 一条命令复现

需要 Python 3.12、MATLAB Reinforcement Learning/Deep Learning Toolbox 和 GCC；本机链路已在 MATLAB R2024b 验证，使用 Instrument Control Toolbox 的 TCP 接口。串口模式另需 pyserial。Mock 不需要电机、串口或 Python 深度学习库。

从仓库根目录运行，`OUTPUT` 替换为项目规定的独立临时目录：

```text
python -B skills/motor-td3-serial-tuning/scripts/run_mock.py --output OUTPUT --rounds 6
```

MATLAB/GCC 不在 PATH 时增加 `--matlab MATLAB_EXECUTABLE --compiler GCC_EXECUTABLE`。使用新的空输出目录。

入口会启动模拟桥接器，调用真正的 MATLAB TD3，保存检查点，执行无探索的固定 PI/TD3 对比，导出 Actor C 文件并编译对齐 MATLAB 参考值。查看 `OUTPUT/run-summary.json`。

## 验证结果

仓库保存了 [模拟验证摘要与模型](examples/mock-validation)。它们可用于复现与检查代码，禁止直接上实机。

| 检查 | 结果 |
|---|---|
| MATLAB TD3 训练（原始设置） | 6 轮，180 条经确认经验，Actor 权重变化 L2 ≈ 0.0882；候选没有超过固定 PI |
| MATLAB TD3 训练（方向覆盖 + 安全代价） | 20 轮，600 条经确认经验，Actor 权重变化 L2 ≈ 2.7335；候选超过固定 PI |
| 训练和评估经验审计 | 780 条，时序/参数/回合链审计通过 |
| Python 桥接测试 | 14 项故障/通信测试通过 |
| MCU C 主机测试 | 19 项协议/保护检查通过 |
| MATLAB/C 推理对齐 | 40 组输入通过，NaN 被拒绝 |
| 独立工况平均归一化 RMSE | 固定 PI 0.171695；代价感知 TD3 0.166923 |

原始设置的问题是：局部增益动作每步只改变 `8e-5`，却使用独立零均值噪声；30 步回合的增益轨迹大多停留在基准附近，几乎没有覆盖高增益区域。网格检查发现 mock 对象的较优区域在 `Kp≈0.0043、Ki≈0.0022`，靠近边界。每轮只有 20 个训练步，也不足以让双 Critic 学会这个局部动作映射。

已改进模拟训练：仅在模拟对象中加入有界的方向性覆盖（四个角方向循环）和随机噪声，并在 128 条经验后使用 3 个 epoch、每 epoch 100 个训练步；奖励同时记录跟踪误差、电流均方值、峰值电流、过冲和饱和持续时间；真实串口仍保持小幅零均值噪声和更保守的训练计划。新的 20 轮结果：固定 PI 平均归一化 RMSE `0.171695`，TD3 `0.166923`，下降约 `2.78%`；三个工况分别从 `0.103565/0.169576/0.241945` 降至 `0.100370/0.164339/0.236059`。候选峰值电流为 `1.732/2.775/3.000 A`，基准为 `1.698/2.717/3.000 A`，最重工况饱和占比为 `3.00%` 对 `2.67%`；误差下降没有带来电流风险指标的同步下降。这是 mock 结果，不能直接推断真实电机效果。

改进解决的是数据覆盖和训练预算问题，不是把网络自动批准为电机控制器。新 Actor 仍需独立评估、RAM/SIL/PIL、保护验证和真实基准对比。

### 论文启发与当前取舍

- [EMTD3 自动 PID 调参](https://arxiv.org/abs/2210.02381)提出先用熵最大化的随机 Actor 探索，再切换确定性 Actor。我们在这个局部 Kp/Ki mock 上试过全随机暖启动，四角覆盖反而变差，因此当前实现保留可复现的方向覆盖；这不是把 EMTD3 论文直接宣称为已实现。
- [DC 电机 TD3-PI 研究](https://www.sciencedirect.com/science/article/pii/S0957417422022102)强调参考值滤波和随机负载扰动。当前 mock 已有种子化的惯量/负载变化；加入额外负载脉冲的实验没有改善这三个名义工况，下一步应在包含真实负载观测的模型上单独评估，不能用未观测扰动硬塞进实机训练。
- [Robust Action Governor](https://arxiv.org/abs/2102.10643)把安全监督器放在策略外层。仓库的增益边界、步长、应用回读、动作租约、停机确认和 MCU 独立保护就是这个原则的工程实现；奖励里的安全代价只是学习信号，不能替代保护。

这轮改进先选择了可验证的安全代价奖励。Codex 会同时分析 RMSE、峰值电流、饱和、过冲和故障，而不是只看一个训练分数；候选在任一项恶化时仍保持“待验证”状态。

## 参考论文

| 论文 | 对本项目的参考价值 |
|---|---|
| Fujimoto、van Hoof、Meger，*Addressing Function Approximation Error in Actor-Critic Methods*，[TD3 原论文](https://arxiv.org/abs/1802.09477) | 双 Critic、延迟 Actor 更新和目标策略平滑的算法基础。 |
| Chowdhury、Lu，*A Novel Entropy-Maximizing TD3-based Reinforcement Learning for Automatic PID Tuning*，[论文](https://arxiv.org/abs/2210.02381) | 提出随机 Actor 暖启动再切换确定性 Actor，用于改善 PID 调参的探索效率。本项目实测后保留方向覆盖，因为全随机暖启动在当前局部 Kp/Ki mock 中效果更差。 |
| Tufenkci 等，*A theoretical demonstration for reinforcement learning of PI control dynamics for optimal speed control of DC motors by using Twin Delay Deep Deterministic Policy Gradient Algorithm*，[论文](https://www.sciencedirect.com/science/article/pii/S0957417422022102) | 参考值滤波、PI 观测状态和随机负载扰动的电机速度控制环境设计。 |
| Li 等，*Safe Reinforcement Learning Using Robust Action Governor*，[论文](https://arxiv.org/abs/2102.10643) | 强调把安全监督器放在策略外层；本项目的增益边界、步长限制、应用回读、租约和 MCU 独立停机按这一原则设计。 |

论文只提供算法和实验设计参考，不能替代目标电机的参数辨识、保护验收或实机闭环测试。论文中的随机探索、扰动幅度和奖励权重不能直接复制到 STM32 板上。

### 为什么没有直接换 PPO

PPO 和 TD3 的区别发生在训练阶段；部署到板子上时只保留 Actor，PPO 的 Critic、TD3 的双 Critic 和回放池都不放进 MCU。PPO 的均值 Actor 可以导出成类似的 C 推理网络，但 PPO 是 on-policy，通常需要更多新样本；在真实电机上采样昂贵且有风险。当前任务的连续 Kp/Ki 动作和离策略经验更适合先修正 TD3 的探索覆盖，再用相同工况、相同数据预算做 PPO 对照。只有 PPO 在未参与训练的负载、给定和保护边界上稳定优于 TD3，才考虑替换；不能因为“PPO 能部署”就认为它更安全。

GitHub Actions 自动运行不需要 MATLAB 的桥接、MCU 主机和已发布 Actor 数值检查。MATLAB 全链路需在有工具箱许可的本机运行。

### STM32G431 板上实测

Codex 查阅板卡原理图与安全说明，经 STLink 核对芯片后，将已训练 Actor 编译并加载到 **MCU SRAM**，在功率电源断开的条件下运行测试，分析以下结果：

| 检查 | 实测结果 |
|---|---|
| MCU 与 MATLAB 推理比较 | 40 组全部通过 |
| 最大动作绝对误差 | `5.960464477 × 10⁻⁸` |
| 最大 Kp/Ki 绝对误差 | `0` |
| 异常输入 | NaN、Infinity、越界增益全部被拒绝 |
| 单次推理周期 | 11,523～11,932 个 CPU 周期 |
| 栈最大观测占用 | 456B / 1,024B 保留空间，栈底检查通过 |
| 完整测试镜像 | 12,844B，包含网络、数学库和测试向量 |
| 测试结束 | PWM 关闭、核心暂停、原 Flash 逐字节一致 |

**这已验证 Actor 能在实际单片机上运行。** 测试使用 RAM、复位默认时钟和屏蔽中断；观测周期/栈占用不代表生产 FOC 固件的最坏情况。没有进行串口闭环训练、应用网络增益或写入 Flash。

[板卡检查与实测报告](docs/stm32g431-validation.md) · [可复用 RAM 部署/PIL 流程](skills/motor-td3-serial-tuning/references/stm32-ram-pil.md) · [机器可读摘要](examples/stm32g431-pil/summary.json)

### 原固件空载试转

2026-10-10，Codex 在用户授权的 STM32G431 板上完成了一次受限空载试转。Codex 通过 STLink 读取 MCU SRAM 和 TIM1 寄存器，分析母线、Hall 状态、速度、三相电流和 PWM 状态，并在结束时执行复位暂停，确认三相 PWM 已关闭。观测到母线约 24.1 V、速度约 950–1050 rpm、Hall 六状态连续有效、相电流约在 ±1.1 A 内；试验没有烧录 Flash，也没有让 TD3 接管电机。

详细记录见 [STM32G431 原固件空载试转记录](docs/stm32g431-spin-test.md)。这次结果说明 **Codex 可以读取并分析真实电机运行结果、判断停机条件并管理安全收尾**；TD3 实机训练仍需目标固件提供原子增益写入、应用回读、失联租约和独立保护，原有 UART3 协议不能直接用于 TD3 接管。

随后在断开 24 V、只保留 USB/STLink 的条件下检查了原固件 USER3/PC13 停机路径。默认状态和 TIM1 功率输出均为关闭，但测试窗口没有观测到按键切换；因此 USER3 尚未被认定为可靠的唯一急停路径。详见 [USER3 停机路径检查](docs/legacy-button-safety-check.md)。

## 组成

| 位置 | 内容 |
|---|---|
| `skills/motor-td3-serial-tuning/SKILL.md` | Codex 工作规程与触发说明 |
| `scripts/motor_runtime.py` | 持久串口监督器、mock、认证 TCP、因果经验 |
| `matlab/trainMotorTD3.m` | 小型 Actor、双 Critic、真实 TD3 更新 |
| `matlab/evaluateCheckpoint.m` | 已选定检查点的固定策略评估 |
| `matlab/exportMotorActor.m` | Actor 权重、尺度和参考输出 |
| `scripts/actor_codegen.py` | 无动态内存 C99 导出与主机编译检查 |
| `scripts/stm32_actor_pil.py` | G431/G441 目标编译、RAM 部署、MCU 推理/周期/栈验证 |
| `scripts/legacy_hall_monitor.py` | 当前 STM32G4 原固件的只读 24 字节 Hall 遥测解析；不发送启动或增益命令 |
| `scripts/can_monitor.py` | PCAN 静默监听、驱动模式回读和原始帧记录；不发送 CAN 控制帧 |
| `firmware/` | CRC 协议、参数保护、租约/失联/故障锁存 C 模块 |
| `scripts/session_checks.py` | 配置与经验审计 |
| `assets/` | 未配置的实机模板、仅用于模拟的配置 |

[运行方法、输入输出与实机入口](skills/motor-td3-serial-tuning/references/matlab-runtime.md) · [STM32 接入说明](skills/motor-td3-serial-tuning/references/firmware-integration.md)

## 安装为 Codex skill

将 `skills/motor-td3-serial-tuning` 整个目录复制到 Codex skills 目录，或让 Codex 安装该仓库中的这个目录。

```text
使用 $motor-td3-serial-tuning，把我的电机串口接入 MATLAB TD3，
先检查工程和保护，用 mock 验证链路，再安排受限实机试验。
```

Skill 安装不会启动电机。真实串口运行需要完整设备配置和已有用户运动授权，明确选择 `--transport serial --allow-live`。旧的 P3/P4 单参数写入协议没有应用确认和租约，不能直接用于这个训练器。

## 实机和部署

实机前需接入目标固件的原子参数写入、实际反馈、独立过流/急停、失联/动作租约和停机路径，填好基准/增益步长、电流、转速、电压、温度、持续时间及来源证据。Mock 配置会被实机入口拒绝。

Actor 是 `10 → 16 → 16 → 2` 的小网络，仅权重约 1.9 KB。部署保留 FOC/PI，把网络作为慢速增益调度器。本仓库提供 G431/G441 的计算专用 RAM 部署入口，已在实际 G431 上验证；永久部署的板级 HAL、观测输入、独立保护和下载配置须按实际工程接入。

Codex 可在目标条件齐全的已授权会话中完成导出、工程接入、编译、烧录和结果分析。本次完成的是 **RAM 中运行 Actor**；尚未把它烧录成常驻电机控制固件。原固件与电机保护没有被替换。

原始遥测、令牌、私有工程和训练检查点不上传公开仓库。

当前板上原固件的只读串口布局见 [legacy-board-telemetry.md](docs/legacy-board-telemetry.md)。它只适合 shadow 观测，缺少 TD3 所需的动作应用确认和独立停机协议。

CAN 是另一条可接入 MATLAB 的通信路径。对应原固件的工程已包含 500 kbit/s 经典 CAN，发送扩展 ID `0x1B`、8 字节占位帧；尚未实现 TD3 增益应用确认或通信保护。本项目提供 [PCAN 静默监听器](scripts/can_monitor.py)：初始化前设置并核验 Listen-Only，初始化后回读，并拒绝被其他程序占用的通道。板卡资料包含接口不同的两版原理图，接线须先核对板卡丝印；详见 [CAN 接入与验证状态](docs/stm32g4-can-path.md)。

## 独立测试

```text
python -B skills/motor-td3-serial-tuning/scripts/session_checks.py self-test
python -B skills/motor-td3-serial-tuning/scripts/test_runtime.py --output TEST_OUTPUT
python -B skills/motor-td3-serial-tuning/scripts/test_firmware.py --output C_TEST_OUTPUT --compiler gcc
```

## 依据

- [AI Parameter Tuning](https://github.com/YANG985-CMD/AI-Parameter-Tuning)：原有串口调参思路。
- [TD3 论文](https://arxiv.org/abs/1802.09477)：算法依据。
- [EMTD3 自动 PID 调参](https://arxiv.org/abs/2210.02381)：探索到利用的阶段化参考。
- [DC 电机 TD3-PI 与随机扰动](https://www.sciencedirect.com/science/article/pii/S0957417422022102)：电机速度控制环境设计参考。
- [Robust Action Governor](https://arxiv.org/abs/2102.10643)：策略外安全监督参考。
- [MathWorks TD3 Agent](https://www.mathworks.com/help/reinforcement-learning/ref/rl.agent.rltd3agent.html) 和 [trainFromData](https://www.mathworks.com/help/reinforcement-learning/ref/trainfromdata.html)：实际训练接口。
- [MathWorks 已部署策略的学习](https://www.mathworks.com/help/reinforcement-learning/ug/fine-tune-deployed-policy.html)：通信与学习解耦参考。
