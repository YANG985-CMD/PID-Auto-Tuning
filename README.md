# PID 参数自整定：四种可移植方法的实现与对比

以电机速度环为例，对比 **AI skill 有界搜索、模糊 PID、神经网络 PID 和 TD3 Actor** 四种 PID 参数自整定方法。当前示例采用 PI 形式（Kd=0），调整 Kp、Ki，固定 PI 作为比较基线。

**四种方法都可以由使用者借助 AI 移植到自己的控制对象和板卡。** 参数调节由 AI（Codex）组织完成，涵盖模糊 PID 的规则与隶属函数参数调整，以及神经网络 PID、TD3 Actor 的超参数选择、训练和评估。AI skill 有界搜索与 TD3 Actor 是本仓库重点构建的创新工程方案；目标条件满足后，Codex 可继续完成目标工程接入与部署。

## 四种方法的结果对比

以下表格对应当前代码保存的仿真/离线评估结果。AI 搜索、模糊 PID 和神经网络 PID 由比较脚本计算，TD3 行读取 MATLAB 固定策略评估摘要。

| 方法 | 平均归一化 RMSE | 平均峰值电流 (A) | 平均过冲 (rpm) | 饱和占比 | 故障 |
|---|---:|---:|---:|---:|---:|
| 固定 PI 基线 | 0.174773 | 2.4717 | 0.000 | 0.0089 | 0 |
| AI skill 有界搜索 | 0.171898 | 2.3806 | 0.799 | 0.0072 | 0 |
| 模糊 PID | 0.165461 | 2.7177 | 0.000 | 0.0194 | 0 |
| 神经网络 PID | 0.164814 | 2.6925 | 0.000 | 0.0178 | 0 |
| TD3 Actor | 0.166923 | 2.5023 | 0.000 | 0.0100 | 0 |

在这组结果中，神经网络 PID 的平均 RMSE 最低；AI skill 有界搜索的平均峰值电流和饱和占比最低。结果用于比较跟踪性能与控制代价，未形成四种方法的实机排名。

[完整对比报告](examples/controller-comparison-20261011/comparison.md) · [JSON 指标](examples/controller-comparison-20261011/comparison-report.json) · [CSV 数据](examples/controller-comparison-20261011/comparison.csv)

## 复现与移植入口

- [四种方法的流程、创新说明、论文依据和复现命令](docs/pid-self-tuning-methods.md)
- [PID 参数自整定 Codex skill](skills/controller-hyperparameter-comparison/SKILL.md)
- [独立实验日志归档](docs/experiment-archive/README.md)
