# SpeedLoop 看门狗集成与真实 CAN 心跳失联验证

日期：2026-10-11。Codex 在用户 STM32G431 板上构建、烧录并验证了禁止运动的 `g431-speedloop-wdog-v1`。原 `17.SpeedLoop` 工程保持不变；本次没有启动电机、应用增益、运行 Actor 或产生 TD3 学习经验。

## 已完成的工作

| 项目 | 实测结果 |
|---|---|
| 最终镜像 | 49 个编译单元，35620B；完整烧录回读一致 |
| 健康运行 | 约 600ms：60 次有效 ADC、60 次前台喂狗，故障为 0 |
| 停止 ADC 更新 | ADC 超时 fault=6，停止喂狗，捕获新 IWDG 复位 |
| 前台卡死、保留中断 | 前台/喂狗计数不再增加，SysTick 锁存故障，捕获 IWDG 复位 |
| 关闭可屏蔽中断并卡死 | 时钟/前台/喂狗计数不再增加，IWDG 仍独立复位 |
| 真实 CAN 健康窗口 | 500 kbit/s 经典 CAN；合法 HELLO、9 组完整四帧诊断、13 次有序 STOP 心跳 |
| 停止应用层心跳 | 保留物理 CAN 和正常 ACK；板端 fault=7、link_seq=13、停止喂狗并产生 IWDG 复位 |
| 复位后的检查 | 在 HAL/外设初始化前保持禁止启动；100ms 观察窗口内 active=0、feeds=0、boot_latched=1 |
| 收尾 | 先暂停已核验固件并关闭输出，再释放 CAN；用户断电后复位暂停、清复位标志，两次镜像回读一致，选项字节与原调试冻结设置不变 |

最终 BIN SHA256：

```text
ea6bb46181092ed415cdcc804ceccac6c14fdedfa8861d3797f1f6fa9c41e54d
```

健康 CAN 窗口中的标称母线为 24.089～24.236V、ADC 年龄 1ms、Hall 速度 0rpm。标称相电流最大值 0.0659A 是未完成外部增益标定的诊断换算，不能当成保护阈值或精确电流。

[断电测试摘要](../examples/stm32g431-speedloop-watchdog/power-off-summary.json) · [真实 CAN 摘要](../examples/stm32g431-speedloop-watchdog/can-summary.json) · [最终状态](../examples/stm32g431-speedloop-watchdog/final-state.json) · [构建指纹](../examples/stm32g431-speedloop-watchdog/build-summary.json)

## Codex 如何定位并修正问题

1. **初始化误报：**初版将 IWDG 寄存器同步等待计入 5ms 前台期限，第一轮前台尚未开始就报超时。把健康监督起点移到寄存器同步完成后，并添加 6ms 延迟回归用例。
2. **连续诊断缺帧：**初次外部 CAN 的第四组缺少 0x623，采集器立即拒绝。原实现只检查 HAL 入队成功，便推进诊断帧索引；现在保持一个待发送请求，以实际 Tx Event 确认完成。
3. **DAR 模式的合法事件被误判：**新增完成检查最初只接受 ET=01；实测保存的首帧事件却是 ET=10、ID=0x621、marker=1、DLC=8。查阅 ST RM0440 后确认：关闭自动重传的 DAR 模式成功发送也产生 ET=10。当前副本改为开启硬件自动重传，正常完成事件为 ET=01，同时保留 marker/ID/格式检查和 50ms 发送超时。
4. **原缺帧的原因判断：**DAR 模式会在仲裁失败后取消请求，而 HAL 入队并不保证发送成功。主机 STOP 的 ID=0x620 优先于诊断帧，这与原缺帧现象相符；该次仲裁丢失没有逐帧测量，因此这是原因推断。改用完成确认及有期限的硬件重传后，9 组连续诊断完整。
5. **镜像回读异常：**一次批量回读有 362 字节不一致，独立重读恢复一致；没有因此发送 CAN 命令。现要求两次完整镜像回读都匹配，任一次不一致即拒绝；具体调试读取异常的来源未确认。
6. **故障证据锁存：**保存首个发送故障和事件，避免后续超时覆盖原因；协议故障也单独锁存，避免默认 NOT_READY 掩盖异常心跳。

失败记录不会并入成功数据。[拒绝的尝试与修正](../examples/stm32g431-speedloop-watchdog/rejected-attempts.json)

ST [RM0440](https://www.st.com/resource/en/reference_manual/dm00355726.pdf) 的 DAR 模式和 Tx Event FIFO 说明支持上述发送行为；[G4 HAL 源码](https://github.com/STMicroelectronics/stm32g4xx-hal-driver/blob/master/Src/stm32g4xx_hal_fdcan.c) 区分发送入队与事件读取。

## 软件与硬件证据的区别

- 实际适配层加软件 HAL/CMSIS 替身：15 项看门狗/协议/发送完成检查通过。
- 原 SpeedLoop 适配层：26 项检查通过；CAN C 端点与主机协议：16 项通过。
- 烧录/CAN 入口的供电与证据拒绝：8 项；原连续采集器：9 项通过。
- 上述软件测试不操作硬件。表格中的复位、通信及回读来自实际板子，两类证据分别保存。

[软件摘要](../examples/stm32g431-speedloop-watchdog/software-summary.json) · [复用步骤](../skills/motor-td3-serial-tuning/references/speedloop-watchdog.md)

## 尚需验证

这是禁止运动的完整诊断固件：移除了 PWM 启动和 FOC 执行入口，软件 ADC 约 100Hz，能力为 0。通信实验是停止应用心跳，未物理拔线；IWDG 捕获发生在暂停调试器配合下，测试时关闭 IWDG 调试冻结。

5ms/30ms/200ms 期限和约 200ms IWDG 是诊断设定，没有测量运动中的功率输出关闭延迟、电流衰减或最坏停止时间。真实 FOC 时序、实体急停、电流标定/过流门槛、热保护、原子增益应用回读和真实基准比较仍需验收，完成后才能进行受限实机 TD3。

Codex 在本次承担源码检查、保护集成、编译烧录、数据分析、原因定位及证据整理。前期 Actor 已通过 MCU RAM 推理；本次 Flash 中是保护诊断固件，尚未把 TD3 Actor 部署成常驻电机闭环策略。
