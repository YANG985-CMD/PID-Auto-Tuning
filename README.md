# Motor TD3 Serial → MATLAB → MCU

把电机串口数据送进 MATLAB 训练 TD3，输出有界的速度环 Kp、Ki，经串口应用确认后形成学习经验；Codex 管理实验和分析结果，最终导出仅用于推理的 Actor C 代码。

**现在包含可运行程序。已用模拟设备跑通真实 MATLAB TD3 训练、独立评估和 C 推理一致性检查；尚未连接实际电机或烧录开发板。**

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
> 本项目用于电机控制研究、仿真和经过验证的受限实验。当前公开结果来自模拟设备与主机测试，尚未完成具体电机和开发板的实机验证，不构成实机安全、闭环稳定性或调参性能保证。

- **示例仅供演示：**模拟配置、PI 参数和示例网络不能直接用于真实电机；当前短训 TD3 没有优于固定 PI。
- **实机使用须先验证：**针对目标电机、驱动器和负载确认基准、参数边界、变化步长及电流/转速/电压/温度/持续时间限制，并验证原子参数更新、实际应用回读、独立过流、急停、失联保护和动作租约。
- **实验须明确授权并限制范围：**实机试验在已授权的工况、时间和动作预算内进行；发生故障先执行经验证的停机路径，禁止自动清故障或重启。
- **实时保护由 MCU 执行：**Codex 管理本地桥接和训练程序，不能代替 MCU 的实时闭环、独立保护或现场急停。
- **部署以独立验证为依据：**候选网络须与已验证控制器进行独立比较，并完成目标编译、内存/执行时间检查及 SIL/PIL；主机数值对齐不等于上板验收。

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
| MATLAB TD3 训练 | 6 轮，180 条经确认经验，Actor 权重变化 L2 ≈ 0.0882 |
| 训练和评估经验审计 | 360 条，时序/参数/回合链审计通过 |
| Python 桥接测试 | 13 项故障/通信测试通过 |
| MCU C 主机测试 | 19 项协议/保护检查通过 |
| MATLAB/C 推理对齐 | 40 组输入通过，NaN 被拒绝 |
| 独立工况平均归一化 RMSE | 固定 PI 0.171695；短训 TD3 0.171713 |

**这次短训网络没有优于固定 PI。** 结果验证了学习与导出链路，不能据此认定网络调参效果更好、实际电机稳定或已经通过部署验收。

GitHub Actions 自动运行不需要 MATLAB 的桥接、MCU 主机和已发布 Actor 数值检查。MATLAB 全链路需在有工具箱许可的本机运行。

## 组成

| 位置 | 内容 |
|---|---|
| `skills/motor-td3-serial-tuning/SKILL.md` | Codex 工作规程与触发说明 |
| `scripts/motor_runtime.py` | 持久串口监督器、mock、认证 TCP、因果经验 |
| `matlab/trainMotorTD3.m` | 小型 Actor、双 Critic、真实 TD3 更新 |
| `matlab/evaluateCheckpoint.m` | 已选定检查点的固定策略评估 |
| `matlab/exportMotorActor.m` | Actor 权重、尺度和参考输出 |
| `scripts/actor_codegen.py` | 无动态内存 C99 导出与主机编译检查 |
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

Actor 是 `10 → 16 → 16 → 2` 的小网络，仅权重约 1.9 KB。部署保留 FOC/PI，把网络作为慢速增益调度器。主机 C 对齐后仍需目标编译、执行时间/内存检查与 SIL/PIL；板级 HAL 和下载器须按实际工程接入。本仓库没有通用的自动烧录配置。

原始遥测、令牌、私有工程和训练检查点不上传公开仓库。

## 独立测试

```text
python -B skills/motor-td3-serial-tuning/scripts/session_checks.py self-test
python -B skills/motor-td3-serial-tuning/scripts/test_runtime.py --output TEST_OUTPUT
python -B skills/motor-td3-serial-tuning/scripts/test_firmware.py --output C_TEST_OUTPUT --compiler gcc
```

## 依据

- [AI Parameter Tuning](https://github.com/YANG985-CMD/AI-Parameter-Tuning)：原有串口调参思路。
- [TD3 论文](https://arxiv.org/abs/1802.09477)：算法依据。
- [MathWorks TD3 Agent](https://www.mathworks.com/help/reinforcement-learning/ref/rl.agent.rltd3agent.html) 和 [trainFromData](https://www.mathworks.com/help/reinforcement-learning/ref/trainfromdata.html)：实际训练接口。
- [MathWorks 已部署策略的学习](https://www.mathworks.com/help/reinforcement-learning/ug/fine-tune-deployed-policy.html)：通信与学习解耦参考。
