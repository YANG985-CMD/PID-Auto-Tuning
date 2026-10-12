# PID 参数自整定：四种方法与可移植实现

[结果对比](../README.md) · [Codex skill](../skills/controller-hyperparameter-comparison/SKILL.md)

## 本仓库的创新方法

**AI skill 有界搜索和 TD3 Actor 是本仓库重点构建的两种 PID 参数自整定创新方法。** 创新集中在响应数据分析、闭环参数调整、实际应用反馈和可移植部署的工程流程，模糊 PID 与神经网络 PID 用于方法对照。

- **AI skill 有界搜索：** 将 GPT-6.1-sol 的波形分析与有界参数搜索结合，通过“串口采集 → 波形分析 → 候选生成 → 约束检查 → 参数下发 → 实际应用回读 → 效果评估”形成可审计的 PID 自整定闭环。
- **TD3 Actor：** 以已有 TD3 算法为基础，构建由 **Codex 驱动的自动训练、自动结果分析和自动部署**流程。Codex 自动配置 MCU/Python 数据链路、审计动作与响应的对应关系、调用 MATLAB 训练并执行固定策略评估、分析和筛选候选，再导出 Actor JSON/C99 推理代码、接入目标工程并执行编译、烧录和部署验证。目标接口、编译链与保护条件齐全并具备用户授权时，使用者可以让 Codex 完成从响应数据到目标 MCU 的 PID 自整定训练与部署。

两种创新方案都面向使用者提供移植路径，可按目标控制对象、PID 参数边界、通信协议和 MCU 实时周期进行适配。算法基础与论文依据见文末参考文献。

## 四种自整定方法的工作流程

### 1. AI skill 有界搜索（本仓库创新方法）

这是一个“读取数据 → 分析波形 → 生成候选 → 串口下发 → 验证结果”的闭环调参器。Python 串口桥接器读取速度、给定值、电流、母线、故障、当前实际 Kp/Ki、序号和时间戳；高频原始帧保存在本地，再按窗口整理成稳态误差、RMSE、上升/稳定时间、过冲、峰值电流、饱和比例和故障摘要。

本项目使用 **GPT-6.1-sol** 分析结构化波形摘要和必要的数据窗口，提出 PID 增益的有界候选；当前电机示例调整 Kp、Ki。主机侧安全门检查上下限、单步变化、动作租约、故障状态和停机条件，再通过串口发送带校验的原子参数命令。MCU 返回实际应用值、序号和时间；候选恶化或违反约束时回退到已验证参数。

GPT-6.1-sol 负责低频的波形理解和候选搜索，实时控制、参数限幅和独立保护仍由目标设备执行。迁移到其他控制器时，替换串口协议、观测字段、参数边界和目标函数即可。

### 2. 模糊 PID

误差 `e` 和误差变化率 `de` 先归一化并截断到 `[-1,1]`，再使用七个语言变量 `NB/NM/NS/ZO/PS/PM/PB`。内部语言变量使用重叠三角隶属函数，两端使用梯形隶属函数。两个输入形成 `7×7=49` 个规则组合；规则根据误差大小和变化趋势给出 `ΔKp`、`ΔKi`。

规则激活度采用乘积或最小值，输出采用离散重心/加权平均解模糊：

```text
ΔKp = Σ(activation[i,j] × ΔKp_rule[i,j]) / Σ activation[i,j]
ΔKi = Σ(activation[i,j] × ΔKi_rule[i,j]) / Σ activation[i,j]
Kp  = clip(Kp_base × (1 + ΔKp), Kp_min, Kp_max)
Ki  = clip(Ki_base × (1 + ΔKi), Ki_min, Ki_max)
```

代码使用 7×7 显式规则面、三角/梯形隶属函数和有界输出。论文改进路线是用多工况数据优化隶属函数断点和规则表，并比较 5×5、7×7 与稀疏规则在误差、过冲、计算周期和内存上的折中。规则表、隶属度计算和解模糊逻辑都可以移植为 MCU 查表或定点实现。

### 3. 神经网络 PID

本仓库把神经网络 PID 定义为一个可审计的监督学习调度器。网络输入是五个归一化特征：误差、误差变化量、积分状态、当前速度和目标速度；当前结构为 `5 → 16 → 16 → 2`，输出经过线性缩放得到有界 Kp、Ki。

网络在主机侧学习已检查过的模糊 PID 调度，并使用训练/验证划分；代码还对训练范围外的状态回退到模糊调度，避免直接外推。板端只运行固定权重的前向推理，不运行反向传播，也不直接输出 PWM。迁移时重新生成覆盖目标工况的数据，验证输入缩放、量化误差、执行时间、内存和异常回退即可。

### 4. TD3 Actor（本仓库创新方法）

TD3 将 PID 参数自整定建模为连续动作学习问题，Actor 根据控制状态输出有界的 PID 增益调整；当前示例的动作为 Kp、Ki 调整。Actor、双 Critic、经验回放和目标网络在主机侧训练；部署到设备时只保留有界 Actor 推理。完整流程是：

**使用者可以通过 Codex 自动完成训练和部署。** Codex 配置并启动采集与训练程序，调用 MATLAB 完成 TD3 更新，读取日志、比较候选与基准的性能，并将通过评估的 Actor 导出为目标 MCU 的推理代码。在目标工程接入和设备验证条件满足后，Codex 继续完成编译、烧录、实际运行核验及部署结果分析；MATLAB 执行梯度更新，MCU 执行实时控制与独立保护。

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
