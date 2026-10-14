# 四种调参方法的共同电机仿真

在 MATLAB 中进入本目录，运行 `openComparison` 打开模型；运行 `runComparison` 重现五组 6 秒仿真并保存 results。

- `MotorTunerComparison.slx`：AI skill 参数方案回放、模糊 PI、神经网络 PI、冻结 TD3 Actor，以及固定基准 PI。
- `MotorFOCShared.slx`：唯一的共同 PMSM、平均值逆变器、FOC 电流环和外部增益速度 PI，参考用户原始 `17.SpeedLoop`。
- 全部采用 MathWorks 标准模块，无自定义模块库。网络以矩阵增益、求和和激活模块展开；模糊规则采用二维查表。
- 29 个可编辑层的模块重叠与连线穿块检查均为 0。白色 Measurement_Extractor 封装标准信号选择块；所有黑条宽度不超过 8 像素。关闭子系统内容预览，触发标签与输入标签分开。
- 四种方法仅调节速度 PI 的 Kp/Ki，Kd=0；各方法共用相同增益限幅、变化步长和电机对象。TD3 的 Ki 掩码保持为 0，Ki=0.00144。

## 证据范围

AI 模块回放 Codex 审查过的参数方案，聊天模型不在仿真计算环内。神经网络由固定规则监督训练；TD3 使用已有真实数据训练的冻结实验候选。电机机械参数沿用参考设置，未经本电机实测辨识。

`diagram_layout_report.json` 为逐层布局审计，`model_artifact_check.json` 为标准模块和参数检查，`native_tuner_numerical_check.json` 为原生模块数值对照。五组仿真均完成，实际增益满足共同边界和步长。

仿真结果不代表实机改善，也不批准上板。当前 `deployment_allowed=false`，`performance_claim_allowed=false`。本次随暂停进度公开；仍没有实机部署许可。

## 重建

`buildComparison` 读取本机原始参考模型，通过 MathWorks agentic toolkit 的 model_edit 重建；运行已提供的模型无需该重建工具。需要 MATLAB R2024b、Simulink，以及参考电机/逆变器块所属的 MathWorks 产品。缓存和生成中间文件由初始化函数放到 `E:/simulink/_codex_tmp/`。
