# 热诊断固定镜像的断电上板验证

日期：2026-10-11。用户确认 24V 物理断开、USB/STLink 与 CAN 保持连接后，Codex 将禁止运动热诊断镜像写入 STM32G431 Flash，完成全量回读与缺失校准状态检查。没有发送电机启动或增益命令。

## 实测结果

| 检查 | 结果 |
|---|---|
| 固件身份 | `g431-speedloop-heat-can-v1`，能力为 0 |
| 镜像 | 43580 B，下载后及最终完整回读均一致 |
| 正常运行 | 600ms，ADC 计数 60、喂狗次数 60 |
| 前台/IWDG | 故障 0，运行时未调试冻结 |
| 热接入故障 | `calibration`：当前电流标定记录缺失 |
| 热 guard 故障 | `config`：热限值尚无已验证记录 |
| 初始热状态/预算 | 未知，三相预算保持 `null`，有效窗口为 0 |
| 输出 | 运行快照及收尾均 `CEN=0、CCER=0、MOE=0` |
| 收尾 | reset halt，恢复冻结配置，选项字节未变 |

证据：[真实断电烧录与状态](../examples/stm32g431-thermal-diagnostic/flash-summary.json)、[17 项入口及收尾软件检查](../examples/stm32g431-thermal-diagnostic/entry-tests-summary.json)、[目标构建](../examples/thermal-can/build-summary.json)。软件检查使用替身，没有接触硬件；真实 Flash 记录另行标为 `hardware_executed=true`。

编译器检查热接入结构体为 296 B，所有诊断读取位置与本镜像符号/Arm `offsetof` 一致。布局审计对象没有链接进 MCU，固件二进制与此前离线版本完全一致。镜像 SHA256：`69909f289ae5f5bd0f1d4b7fbe888f08f6d2cd3ddc389b363fa99374ca8f9856`。

## Codex 的分析与部署作用

Codex 完成源码/镜像核验、编译布局检查、设备识别、备份、烧录、完整回读和结果分析。正常的原始 ADC 计数与热接入拒绝状态同时出现，说明当前程序没有把未标定的 ADC 码误当作安培累计；预算未知保持未知。

这次部署的是保护诊断固件。TD3 训练结果分析、Actor 导出和 MCU RAM 推理的既有证据仍见 README；训练 Actor 尚未成为 Flash 中的电机闭环策略。

## 有界 CAN 采集流程

专用入口先在断电状态 prepare，运行约 300ms 后核对同一拒绝状态、暂停核心并生成一次性会话。用户确认板端供电后才运行约 3 秒 HELLO/STOP 采集。收尾先确认核心暂停/PWM 关闭，后停止线程和释放 PCAN。带电时不 reset。

当前已完成断电烧录和准备；真实热 CAN 采集须另记实测结果，不能引用合成日志作为板端证据。复现见 [专用流程](../skills/motor-td3-serial-tuning/references/thermal-board-diagnostic.md)。

## 结论范围

验证了固定禁止运动架构中，缺失标定/热配置的拒绝状态在 MCU 实际出现。没有校准相电流增益、验证实际过流安培阈值或热阈值，没有测量运动停机延迟，也没有形成 TD3 训练经验。缺少电流及热依据时不解除拒绝状态。

完整恢复备份和本地固件保存在私有交付目录，不上传厂商工程、二进制、芯片序列号、nonce/token 或原始实测遥测。
