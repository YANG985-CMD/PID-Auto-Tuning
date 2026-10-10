# STM32G431 独立看门狗验证

2026-10-11，用户此前确认 24V 功率电源物理断开、USB/STLink 保持连接。Codex 在这一状态下构建并运行专用 RAM 程序，测试 IWDG 复位；没有重新烧录 Flash、启动电机或应用 TD3 参数。

## 实际板上结果

| 项目 | 保留 SysTick | 关闭全部可屏蔽中断 |
|---|---|---|
| 正常阶段 | 60 次前台喂狗，约 600ms | 60 次前台喂狗，约 600ms |
| 故障注入 | 前台进入不喂狗循环 | 前台进入不喂狗循环并关闭中断 |
| 停止喂狗后新增 SysTick | 204 次 | 0 次 |
| DWT 观测周期 | 3,258,716 | 3,253,256 |
| 按 HSI16 标称估算 | 203.67ms | 203.33ms |
| 新复位原因 | RCC CSR=`0x24000000`，IWDGRSTF=1 | 相同 |
| 复位捕获 | PC=`0x080001D8`，与原 Flash Reset_Handler 一致 | 相同 |
| 核心状态 | Halted，xPSR=`0x01000000`，原应用未初始化 | 相同 |

IWDG 配置为 PR=3（分频 32）、RLR=199、WINR=4095；LSI 标称 32kHz 对应约 200ms。上述时间是按 HSI16 标称频率估算的一次观测，未用示波器校准，也不是器件最坏复位时间或功率桥封波延迟。

原调试设置 `DBGMCU_APB1FZR1=0xC060183F` 包含 IWDG 冻结位。测试明确清除该位，并先清除旧复位原因，避免把旧标志或调试冻结误认为硬件行为。模式 1 证明“SysTick 仍运行”不会让本诊断继续喂狗；模式 2 证明关闭可屏蔽中断后本次 IWDG 仍触发复位。

## 输出隔离和收尾

- RAM 镜像 1160B，SHA256：`036cb363c5ae3e5ad4db072c15dd044aa8e042ac136381ee94b4368ba4bcc51c`。
- guest 不改变相位引脚模式，不启动 TIM1，不执行 CAN、ADC、FOC 或 Actor；六路相位引脚保持复位模拟模式，TIM1 CR1/CCER/BDTR 为 0。
- 每次 IWDG 复位在原 Flash 复位入口捕获，核对向量表地址及核心模式，保持暂停。
- 最终再次 reset halt，恢复调试冻结设置；完整 128KB Flash 前后字节一致，选项字节仍为 `0xFBEFF8AA`。
- 最终核心 Halted；TIM1 CR1=0、CCER=0、BDTR=0。没有自动恢复原应用。

Flash 仍是上一轮禁止运动的 SpeedLoop CAN 诊断版。本次 RAM 测试没有把看门狗永久接入它，也没有把网络部署到 Flash。私人 Flash 备份、原始轨迹和探针身份不上传。

## 已完成的软件部分

新增 `motor_td3_health.c/.h`：前台、时钟和 ADC 均有新进展且未超时才允许喂狗；已验证心跳过期、重复序号、倒退时钟及板级故障都会锁存。故障不能由晚到心跳或普通会话重装恢复。

**15 项 C 检查与 6 项 Python 合同/证据检查通过，已纳入 CI。** Python 检查拒绝输出开启、错误/旧复位原因、错误 PC/异常模式、未暂停核心、调试冻结和镜像不匹配。它们不连接硬件。

监督器只返回喂狗许可，不负责协议认证或实际封波，尚未在 SpeedLoop 中运行；RAM guest 直接喂狗，因此板上 IWDG 结果不能作为监督器或真实 CAN 失联路径的集成证据。

## Codex 的作用和下一步

Codex 核对 ST HAL/CMSIS 配置，发现调试冻结影响，编写独立诊断与监督器，构建 RAM 镜像，管理 STLink 执行、检查复位原因和输出状态，并对比完整 Flash。它把硬件结果与软件检查分别记录，不把看门狗复位视作运动保护验收。

下一步将监督器和 IWDG 接入**禁止运动的 SpeedLoop 副本**，先在断电条件下验证真实前台/ADC 停止、CAN 心跳过期和复位后禁止启动。还需验收热保护、电流标定、物理急停及功率输出停机路径，才能推进固定 PI 的有界基准与 TD3。

[结构化结果](../examples/stm32g431-watchdog/summary.json) · [构建和操作流程](../skills/motor-td3-serial-tuning/references/g431-watchdog.md) · [ST RM0440](https://www.st.com/resource/en/reference_manual/dm00355726.pdf)
