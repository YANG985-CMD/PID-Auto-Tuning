# 17.SpeedLoop 空载基线试验

日期：2026-10-11。Codex 以用户已经确认“运行正常”的 `17.SpeedLoop` 为基准，在 STM32G431 上建立了一个独立的、有界运行副本。原工程文件没有修改，TD3 Actor 没有接入，Kp/Ki 没有通过 CAN 下发。

## Codex 做了什么

- 检查并复制用户的 42 个工程单元，保留原来的 Hall 映射、FOC 模型、模糊 PI、COMP1→TIM1 Break 和名义电流换算。
- 将 USER3 作为唯一的人工启动门；启动前要求 ADC 已有新采样、Hall 状态有效、母线在 18–30 V、CAN 心跳有效。
- 将六路相桥使能改为一次性写入，并加入 3 s 自动停机、Break 停机、失联停机、主循环/采样进展监测和复位后禁止自动重启。
- 用 CAN 只回传运行快照；Codex 负责接收快照、分析速度/电流/故障和确认停机，再释放通信并暂停核心。

## 实测结果

| 项目 | 结果 |
|---|---:|
| 固件 | `g431-speedloop-baseline-3s-v1` |
| STM32 | STM32G431，整片下载回读一致 |
| 母线 | 约 24.17 V |
| 试验时间 | 3000 ms |
| 最终速度 | 约 1036.5 rpm |
| Hall 边沿 | 326 |
| ADC 采样 | 约 68198 次 |
| 名义电流峰值 | 约 1.10 A |
| 速度闭环快照 | 40 |
| 最终故障码 | 0 |
| 自动停机 | 通过；六路 PWM 关闭后才暂停核心 |

运行中出现过一次约 11251.8 rpm 的 Hall 瞬时异常值；它没有持续出现，末帧和闭环样本约为 1036.5 rpm，因此该尖峰只作为传感器异常记录，不作为真实转速结论。

## 边界

电流使用 `17.SpeedLoop` 源码的名义换算系数 `0.02197265625 A/count`，没有做已知电流源标定；板上没有温度传感器，本次没有验证摄氏温度或热阈值。试验验证了基线固件的受限运行和自动收尾，不表示 TD3 已经调参，也不表示可以把 Actor 直接接管电机。

机器可读摘要见 [`examples/speedloop-baseline-20261011/summary.json`](../examples/speedloop-baseline-20261011/summary.json)。

## 追加：17.SpeedLoop UART 实机回读

用户随后按下 USER3，Codex 在 `COM9` 上以 921600 8N1 只读监听 5 s，没有向板子发送启动、停止或增益数据。恢复的旧 SpeedLoop 镜像连续输出了 16,865 个完整遥测帧：参考转速 1000 rpm，Hall 转速范围 939.9–1053.8 rpm，平均 1000.27 rpm；速度误差 MAE 25.18 rpm、RMSE 30.62 rpm，Hall 周期范围 15,183–17,023 ticks。由此确认这次是有效的空载转动数据，串口链路可以作为 MATLAB 的实时观测输入。

这批数据仍只能作为 SpeedLoop 基线。旧 UART 帧没有控制器选择、Kp/Ki 下发、实际增益回读、动作确认或失联租约，因此不能据此宣称 AI 调参、模糊 PID、神经网络 PID 和 TD3 已完成实机对比。机器可读结果见 [`examples/controller-comparison-20261011/real-speedloop-baseline-user3.json`](../examples/controller-comparison-20261011/real-speedloop-baseline-user3.json)。
