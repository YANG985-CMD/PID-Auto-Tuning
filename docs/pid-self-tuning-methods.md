# PID 参数自整定：四种方法与可移植实现

[结果对比](../README.md) · [Codex skill](../skills/controller-hyperparameter-comparison/SKILL.md)

## 本仓库的创新方法

**AI skill 有界搜索和 TD3 Actor 是本仓库重点构建的两种 PID 参数自整定创新方法。** 创新集中在响应数据分析、闭环参数调整、实际应用反馈和可移植部署的工程流程，模糊 PID 与神经网络 PID 用于方法对照。

- **AI skill 有界搜索：** 将 GPT-6.1-sol 的波形分析与有界参数搜索结合，通过“串口采集 → 波形分析 → 候选生成 → 约束检查 → 参数下发 → 实际应用回读 → 效果评估”形成可审计的 PID 自整定闭环。
- **TD3 Actor：** 以已有 TD3 算法为基础，构建由 **Codex 驱动的自动训练、自动结果分析和自动部署**流程。Codex 自动配置 MCU/Python 数据链路、审计动作与响应的对应关系、调用 MATLAB 训练并执行固定策略评估、分析和筛选候选，再导出 Actor JSON/C99 推理代码、接入目标工程并执行编译、烧录和部署验证。目标接口、编译链与保护条件齐全并具备用户授权时，使用者可以让 Codex 完成从响应数据到目标 MCU 的 PID 自整定训练与部署。

两种创新方案都面向使用者提供移植路径，可按目标控制对象、PID 参数边界、通信协议和 MCU 实时周期进行适配。算法基础与论文依据见文末参考文献。

## 四种自整定方法的工作流程

四种方法的调参均由 AI（Codex）组织完成。使用者提供控制对象、可调参数边界和评价目标，Codex 读取响应数据，选择或修改配置，调用程序计算，再依据结果安排下一轮试验。Python/MATLAB 执行搜索、模糊推理和梯度更新，目标设备执行实时控制。

调节分为两层：一层是控制器的 Kp、Ki；另一层是决定“如何产生 Kp、Ki”的方法参数，例如模糊规则、网络结构、学习率和 TD3 噪声。当前比较脚本保存了一组可复现的规则与训练配置；配置的下一轮修改由 Codex 根据结果完成。

### 1. AI skill 有界搜索（本仓库创新方法）

AI 在这一方法中直接决定下一组待试验的 PID 增益。串口闭环按以下步骤执行：

1. **读取与整理。** Python 读取给定、速度、电流、母线、故障、实际 Kp/Ki、序号和时间戳，将波形整理成误差、RMSE、上升/稳定时间、过冲、峰值电流和饱和占比等窗口摘要。
2. **分析与提案。** GPT-6.1-sol 结合摘要、已试参数和允许边界，判断响应迟缓、稳态误差或过冲等问题，提出 Kp/Ki 候选及调整理由。例如，响应偏慢且电流有余量时试验较大的 Kp；过冲或饱和增加时，缩小增益调整或搜索步长。每个提案都要经实际复测判断。
3. **检查与下发。** Python 检查增益边界、单步变化、动作租约及设备状态，再通过串口发送带 CRC 的原子增益命令。MCU 回传实际应用值、序号和时间，将本次参数与随后的响应对应起来。
4. **比较与迭代。** Codex 比较同工况下的误差和控制代价，保留较优参数；候选恶化或违反约束时回退，并据此缩小搜索区域或改变下一轮方向。

表格对应的离线实现位于 [`tune_skill()`](../scripts/controller_comparison.py)。它按 Codex 配置的目标函数执行确定性搜索：先在 Kp/Ki 边界内测试 5×5 个候选，再围绕较优候选测试 5×5 个局部候选，共 50 次参数候选评估；每个候选运行六个训练种子与三个给定组成的 18 个工况。先检查故障、峰值电流和过冲约束，再最小化以下评分，其中 RMSE 为归一化误差：

```text
J = mean(RMSE² + 0.05 × (峰值电流/4)² + 0.02 × (过冲/1000)²
         + 0.04 × 饱和占比 + 0.25 × 故障数)
```

这一仿真入口复现有界搜索，不调用语言模型或串口。串口适配后，GPT-6.1-sol 执行上述波形分析与提案，设备保留实时控制、参数限幅和独立保护。移植时，Codex 修改观测字段、协议、参数边界、步长和评分权重，再用目标响应重新试验。

### 2. 模糊 PID

AI 在这一方法中调整的是“误差如何映射成增益”的规则和尺度。Codex 读取响应后，选择或修改输入归一化尺度、隶属函数中心及宽度、规则输出和增益映射系数，运行同一组工况，比较误差、过冲、电流与饱和情况，再迭代配置。例如，大误差阶段响应偏慢时，检查对应规则的 Kp 修正；误差快速变化且过冲明显时，检查 Ki 修正与输入尺度。运行时由已确定的模糊规则计算增益。

当前 [`fuzzy_gains()`](../scripts/controller_comparison.py) 的配置与计算过程如下：

1. **输入归一化。** 使用误差 `e = ref - speed` 和误差变化量 `de = e - previous_error`，都除以 `max(abs(ref), 1000)` 并截断到 `[-1,1]`。这里的 `de` 是相对于所保存历史误差的差分量；移植时需与目标采样周期及尺度匹配。
2. **隶属函数。** 七个语言变量为 `NB/NM/NS/ZO/PS/PM/PB`，中心为 `[-1, -2/3, -1/3, 0, 1/3, 2/3, 1]`。中间五个使用相邻中心构成的重叠三角函数，两端使用肩形边界；每个输入的隶属度归一化后参与推理。
3. **规则映射。** 两个输入形成 7×7 共 49 条规则。当前规则输出由各语言变量中心 `E[i]`、`D[j]` 生成：

```text
m[i,j]       = clip(0.7 × abs(E[i]) + 0.3 × abs(D[j]), 0, 1)
ΔKp_rule[i,j] = 0.6 × m[i,j]
ΔKi_rule[i,j] = clip(0.5 × (1 - 2 × abs(E[i])) - 0.2 × abs(D[j]), -0.5, 0.5)
```

这组规则在误差较大或变化较快时提高比例修正，并降低积分修正；误差较小时增强积分作用。当前规则按幅值对称设计，系数和中心都是 Codex 可根据新响应修改的调优对象。

4. **推理与解模糊。** 当前代码使用输入隶属度的乘积作为激活度，每条规则输出一个常数，再用加权平均得到修正量，即单点输出的离散重心：

```text
activation[i,j] = μ_error[i] × μ_change[j]
ΔKp = Σ(activation[i,j] × ΔKp_rule[i,j]) / Σ activation[i,j]
ΔKi = Σ(activation[i,j] × ΔKi_rule[i,j]) / Σ activation[i,j]
Kp  = clip(Kp_base × (1 + ΔKp), Kp_min, Kp_max)
Ki  = clip(Ki_base × (1 + ΔKi), Ki_min, Ki_max)
```

5. **评价与移植。** Codex 修改配置后重跑比较，记录对应规则版本和指标，再决定保留或继续调整。当前脚本直接计算保存的七级规则配置；多版本试验由 Codex 组织。移植到 MCU 时，将已验证的隶属函数、规则表、缩放和限幅转换为查表或定点实现，并检查执行时间与数值误差。

论文改进路线是用多工况数据优化断点和规则表，并比较 5×5、7×7 与稀疏规则在控制效果、计算周期和内存上的折中。

### 3. 神经网络 PID

AI 在这一方法中负责准备数据、选择训练超参数、调用训练和解释结果。训练程序学习“控制状态 → 有界 PID 增益”的映射，本示例使用已配置的模糊 PID 调度作为监督目标。

1. **准备数据。** Codex 确定状态范围与输入尺度，调用 [`train_nn()`](../scripts/controller_comparison.py) 生成 6000 个状态样本，由模糊调度器计算目标 Kp/Ki。输入包含归一化误差、误差变化量、积分状态、当前速度和目标速度；目标增益缩放到 `[-1,1]`。
2. **配置超参数。** 当前 `NnPid` 使用 `5 → 16 → 16 → 2` 的 tanh 网络，学习率为 `0.02`，训练 `900` 轮，样本按 80%/20% 划分为 4800 个训练样本与 1200 个验证样本。Codex 可修改网络宽度、输入尺度、学习率、训练轮数和数据覆盖范围，再启动下一轮训练。
3. **更新权重。** Python 根据预测增益与目标增益的平方误差执行反向传播和梯度下降，更新权重及偏置。Codex 读取训练损失和验证损失，检查拟合情况，并调用闭环仿真比较 RMSE、电流、过冲和饱和占比。
4. **根据结果调整。** 拟合不足时检查样本覆盖、网络容量和训练轮数；训练与验证表现差异较大时检查数据划分及模型复杂度；闭环效果不佳时回查监督目标和控制指标。修改后重新训练并比较。当前比较脚本按保存的单组配置训练，多组超参数试验由 Codex 组织。
5. **运行与移植。** 固定权重网络前向推理得到两个输出，再线性映射为边界内的 Kp、Ki；代码对速度、历史误差或积分状态超出训练范围的输入回退到模糊调度。移植时，Codex 重新准备目标工况数据，导出固定权重与前向计算，并核对输入缩放、量化误差、执行时间、内存和回退逻辑。

### 4. TD3 Actor（本仓库创新方法）

AI 在这一方法中负责数据审计、训练超参数配置、候选比较和部署编排；MATLAB 中的 TD3 根据经验数据更新 Actor 与双 Critic，Actor 再根据控制状态输出有界的 Kp/Ki 调整。

1. **确认训练数据的对应关系。** Codex 核对“状态 → 提议动作 → MCU 实际应用增益 → 后续响应 → 奖励”，检查序号、时间戳与响应窗口，将符合条件的数据整理为经验回放，排除参数未确认应用、响应窗口不完整或发生保护介入的数据。
2. **选择并调整训练配置。** Codex 配置状态归一化、增益边界与单步变化、跟踪误差/电流/过冲/饱和等奖励项，以及网络结构、学习率、批量大小、训练更新次数和噪声。探索噪声影响采集时的动作覆盖，目标策略平滑噪声影响训练目标，两者分别配置。

当前 [`createMotorTD3.m`](../skills/motor-td3-serial-tuning/matlab/createMotorTD3.m) 保存的基础配置为：

| 调节项 | 当前基础配置 | Codex 调整时检查什么 |
|---|---|---|
| 状态与 Actor | 10 个归一化状态，`10 → 16 ReLU → 16 ReLU → 2 tanh` | 状态尺度、动作范围、推理时间与内存 |
| Actor / Critic 学习率 | `1e-4` / `1e-3` | 权重变化、Critic 误差和多种子结果 |
| 批量大小 / 回放容量 | `32` / `10000` | 有效经验数量、工况覆盖和训练稳定性 |
| 折扣因子 / 策略更新间隔 | `0.99` / 每 2 次 Critic 更新更新 Actor | 长期奖励与更新稳定性 |
| 目标网络软更新系数 | `0.005` | 目标网络跟随速度与训练波动 |
| 目标平滑噪声标准差 / 截断 | `sqrt(0.2)` / `0.5`，按动作掩码处理 | 动作范围、双 Critic 分歧与验证结果 |

这些默认值随代码保存，Codex 可修改配置并重训。例如，仓库的[目标噪声与行为克隆权重对照入口](../skills/motor-td3-serial-tuning/matlab/studySpeedLoopTD3Noise.m) 将目标噪声配置 `sqrt(0.2)/0.5`、`0.05/0.1`（标准差/截断）与行为克隆权重 `2.5`、`0.25` 组成四组试验，固定数据划分并分别使用种子 `7/17/27`。Codex 调用这些试验，比较动作建议、双 Critic 分歧和验证误差，决定哪些配置进入后续固定策略评估。

3. **调用 MATLAB 更新。** Codex 启动采集与 [`trainMotorTD3.m`](../skills/motor-td3-serial-tuning/matlab/trainMotorTD3.m) 流程，每轮采集后确认停机，再执行梯度更新。MATLAB 从经验池取样、更新双 Critic、延迟更新 Actor，并保存检查点。Codex 读取训练摘要，判断数据覆盖和训练状态，再决定下一轮采集或配置调整。
4. **冻结策略并比较。** Codex 调用 [`evaluateMotorTD3.m`](../skills/motor-td3-serial-tuning/matlab/evaluateMotorTD3.m)，关闭探索，在相同初始条件和独立测试工况下比较候选与基准的跟踪误差、电流、过冲、饱和及故障。训练诊断与闭环表现共同决定候选是否继续验证。
5. **导出与部署。** Codex 调用 [`exportMotorActor.m`](../skills/motor-td3-serial-tuning/matlab/exportMotorActor.m) 导出 Actor JSON，再通过 [`actor_codegen.py`](../skills/motor-td3-serial-tuning/scripts/actor_codegen.py) 生成 C99 推理实现，核对 MATLAB/C 数值一致性，并完成目标工程接入、编译和 PIL/设备验证。目标接口、编译链、保护条件和授权齐全后，可继续完成烧录、运行核验及部署结果分析；设备保留有界 Actor 推理、实时控制和独立保护。

**使用者可以通过 Codex 自动组织上述训练与部署流程。** 各层的分工如下：

```text
MCU：FOC + 速度 PI + 独立保护
           ⇅ 串口 CRC 帧、原子增益命令、实际应用反馈
Python：持续采集、安全监控、动作租约、单一端口所有者
           ⇅ 认证的本机 TCP
MATLAB：Actor 推理 → 有界试验 → 确认停机 → TD3 更新
           ↓
固定策略评估 → Actor JSON → C99 推理 → 目标工程接入/PIL

Codex：自动配置与采集 → 自动调用 MATLAB 训练 → 自动分析与评估
       → Actor 导出与工程接入 → 编译、烧录及部署验证。
```

四种方法的仿真比较入口要求 TD3 评估摘要标记为 simulation-only，并通过统一工况和安全指标检查。实机经验使用独立采集和审计入口，不混入该仿真表。论文改进路线是分阶段探索、加入稳定性拒绝条件、扩展未见负载/给定测试，并在 Actor 外增加动作边界、步长限制和安全监督器。

## 根据论文落实的代码改进

`scripts/controller_comparison.py` 已把论文建议落到四种方法：

| 方法 | 已落实的代码改进 |
|---|---|
| AI skill 有界搜索 | 粗到细的有界搜索、多目标评分、峰值电流/过冲/故障安全门、候选计数和回退条件。 |
| 模糊 PID | 7×7 三角/梯形隶属函数、显式规则面、加权重心解模糊、有界 Kp/Ki。 |
| 神经网络 PID | 监督拟合模糊调度、训练/验证划分、验证损失记录、训练范围外回退。 |
| TD3 Actor | simulation-only 输入门、外部 TD3 评估源、统一测试工况和安全指标审计。 |

论文提供设计方向，仓库代码提供可复现的仿真比较；两者都不能替代目标系统的参数辨识、实时预算和独立保护验证。

详细的论文与改进映射见 [skill 参考](../skills/controller-hyperparameter-comparison/references/method-improvements.md)。

## 运行 PID 参数自整定的统一比较

需要 Python 3.12 和 NumPy。`--td3-evaluation` 是 MATLAB 导出的 simulation-only 评估摘要；脚本不会打开串口、CAN 或 Flash。

```text
python -B scripts/controller_comparison.py --output OUTPUT \
  --td3-evaluation examples/mock-validation/evaluation-summary.json
```

输出文件：

- `comparison-report.json`：方法、工况、指标、改进配置和安全门结果。
- `comparison.csv`：可直接画图或做统计检验的数据。
- `comparison.md`：适合放进实验记录的表格和解释。

仓库已保存一份示例结果：[comparison-report.json](../examples/controller-comparison-20261011/comparison-report.json)、[comparison.csv](../examples/controller-comparison-20261011/comparison.csv)、[comparison.md](../examples/controller-comparison-20261011/comparison.md)。

## 打包成 Codex skill

本仓库提供独立的 [controller-hyperparameter-comparison skill](../skills/controller-hyperparameter-comparison/SKILL.md)。它不绑定某一块电机板，负责：

- 设计四种 PID 参数自整定方法的统一对比实验；
- 把论文建议转成数据、规则、网络和安全门设计；
- 按目标控制器和 MCU 生成可移植的实现方案；
- 比较误差、电流、过冲、饱和、故障、执行时间和内存；
- 保留训练/搜索证据和目标设备接口契约。

在 Codex 中安装 `skills/controller-hyperparameter-comparison` 后，可以这样调用：

```text
使用 $controller-hyperparameter-comparison，比较这四种 PID 参数自整定方法，
然后按照我的控制对象和 MCU 接口给出可移植实现。
```

## 论文参考

- [Physics-Informed Framework for PID Tuning with Large Language Model Agents](https://arxiv.org/abs/2607.26594)：结构化响应特征、控制工程诊断、物理先验和验收标准。
- [Fuzzy Logic Driven Self-Tuned PI Controller for Enhanced Speed Regulation of PMSM Drives](https://doi.org/10.1155/jece/7690514)：7×7 规则、隶属函数和重心解模糊。
- [A New Method for the Speed Control of a Brushless DC Motor Based on Optimized Fuzzy Control](https://doi.org/10.5152/electrica.2026.25063)：离线优化模糊规则和隶属函数。
- [Design of Fuzzy PID Controller Based on Sparse Fuzzy Rule Base](https://doi.org/10.3390/machines11010081)：稀疏规则与计算量折中。
- [A New On-Line PID Tuning Method Using Neural Networks](https://doi.org/10.1016/S1474-6670(17)38283-6)：神经网络估计过程特性并更新 PID。
- [ANN Based Self-Tuned PID-Like Adaptive Controller](https://doi.org/10.1016/j.eswa.2014.06.040)：小型网络、递推适应与参数变化鲁棒性。
- [Addressing Function Approximation Error in Actor-Critic Methods](https://arxiv.org/abs/1802.09477)：TD3 双 Critic、延迟更新和目标策略平滑。
- [A Novel Entropy-Maximizing TD3-based Reinforcement Learning for Automatic PID Tuning](https://arxiv.org/abs/2210.02381)：分阶段探索和 PID 调参。
- [Stability-Preserving Automatic Tuning of PID Control with Reinforcement Learning](https://arxiv.org/abs/2112.15187)：将稳定性纳入 RL 调参过程。
- [Safe Reinforcement Learning Using Robust Action Governor](https://arxiv.org/abs/2102.10643)：在策略外增加安全监督器。

论文中的模型、规则范围、随机探索和奖励权重不能直接当作某块板子的安全参数。移植到目标设备后，需要重新验证输入尺度、参数边界、实时周期、内存、通信和独立保护。
