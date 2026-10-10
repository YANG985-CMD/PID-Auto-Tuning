# Motor TD3 Serial Tuning

面向电机速度环 PI 调参的 Codex skill。将串口数据采集、TD3 训练流程设计、参数应用确认与独立保护整理成可复用的工作规程。

**当前版本提供 skill、配置模板和经验数据审计工具。具体的 TD3 训练器、串口适配器和 MCU 保护实现，需要针对目标工程生成与验证。仓库不包含已训练模型，也不会默认连接或启动电机。**

## 工作结构

```text
电机与 MCU 控制器
    ⇅ 串口遥测、参数命令与应用确认
本地串口监督器
    ├── 持续采集与独立安全检查
    ├── 有效经验 → TD3 训练程序 → 候选参数策略
    └── 经验证的策略 → 有界参数下发

Codex：配置程序、管理实验、分析结果。
MCU：执行电机闭环控制和独立故障保护。
```

TD3 的学习数据必须包含当前状态、实际生效参数、参数应用后的响应、奖励和终止原因。不能把未下发的网络预测与实际电机响应拼成训练经验。

## 包含内容

- 速度环 `Kp、Ki` 动态调参的工作流程。
- 采集、旁路预测、在线训练与固定策略评估的边界。
- 串口单一所有者、原子参数更新、应用回读与设备时间对齐要求。
- 参数范围、变化限制、动作有效期、独立失联保护和故障锁存设计。
- 会话配置模板与 JSONL 经验数据检查器。
- MCU 工程接入检查清单。

## 安装到 Codex

可以向 Codex 发送：

```text
请从 https://github.com/YANG985-CMD/motor-td3-serial-tuning
安装 skills/motor-td3-serial-tuning 目录中的 skill。
```

也可以将 `skills/motor-td3-serial-tuning` 目录复制到自己的 Codex skills 目录。

## 使用示例

```text
使用 $motor-td3-serial-tuning 检查我的电机串口协议，
建立速度环 PI 的 TD3 训练流程，先完成离线验证和保护设计。
```

提供工程目录、协议说明、参数单位、经过验证的基准与限制，可帮助 Codex 建立具体实现。安装 skill 或生成代码不表示已授权实机运动。

## 离线检查

检查器只需要 Python 标准库。以下命令从仓库根目录运行；本版本已在 Python 3.12 上验证。

```bash
python -B skills/motor-td3-serial-tuning/scripts/session_checks.py self-test

python -B skills/motor-td3-serial-tuning/scripts/session_checks.py check-profile \
  skills/motor-td3-serial-tuning/assets/session-profile.example.json
```

模板为 `plan` 模式，边界和保护验证项尚未配置。检查器的 `--live` 参数只检查配置完整性，不连接硬件；直接对模板使用该参数会拒绝实机配置并返回非零状态。

```bash
python -B skills/motor-td3-serial-tuning/scripts/session_checks.py check-profile \
  skills/motor-td3-serial-tuning/assets/session-profile.example.json --live

python -B skills/motor-td3-serial-tuning/scripts/session_checks.py audit-transitions \
  experiment.jsonl --profile session-profile.json
```

JSONL 格式见 [串口与安全规范](skills/motor-td3-serial-tuning/references/serial-and-safety.md)。

## 实机使用前

- 参数和电流、转速、电压、温度限制必须来自目标设备的验证。
- 主机参数校验与 MCU 独立保护同时存在。
- 训练进程不能阻塞故障监控；主机停止响应时 MCU 仍能执行经过验证的停止行为。
- 实机探索在已验证的局部范围内进行，并限制试验时间及动作次数。
- 普通 TD3 的经验回放不保证从覆盖不足的固定日志学出可靠策略。
- 参数限幅与奖励惩罚不能证明闭环稳定。离线自检通过不等于硬件保护通过验证。

示例中的 PI 初值仅用于演示配置和检查器，不是适用于其他电机的推荐参数。

## 目录

```text
skills/motor-td3-serial-tuning/
├── SKILL.md
├── agents/openai.yaml
├── assets/session-profile.example.json
├── references/
│   ├── architecture-and-training.md
│   ├── project-map.md
│   └── serial-and-safety.md
└── scripts/session_checks.py
```

## 设计参考

- [AI Parameter Tuning](https://github.com/YANG985-CMD/AI-Parameter-Tuning)：串口调参与安全契约的基础思路。
- [TD3 原论文](https://arxiv.org/abs/1802.09477)：算法定义。
- [Stable-Baselines3 TD3](https://stable-baselines3.readthedocs.io/en/master/modules/td3.html)：本地训练实现参考。
- [Conservative Q-Learning](https://arxiv.org/abs/2006.04779)：固定日志学习中的分布偏移问题。
