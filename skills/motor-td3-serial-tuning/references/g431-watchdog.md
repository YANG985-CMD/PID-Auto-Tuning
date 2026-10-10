# G431 独立看门狗：断电 RAM 诊断与喂狗监督器

用于已核对的 STM32G431 电机板。先取得电机功率电源物理断开的现场确认，保留 USB/STLink 控制供电；已有会话确认且供电未变化时不重复询问。它会复位、覆盖 SRAM，并最终保持核心暂停。不要自动恢复原应用。

## 两项验证的范围

| 项目 | 做什么 | 不代表什么 |
|---|---|---|
| `motor_td3_health.c/.h` | 主机 C 检查前台、时钟、ADC 进展及已验证心跳期限；控制是否允许喂狗，故障锁存 | 模块自身不执行封波、协议校验或自动复位；已接入禁止运动 SpeedLoop 诊断副本 |
| `stm32_g431_watchdog.c/.S` | 专用 RAM 程序直接验证 IWDG 硬件复位：先正常喂狗，再停止喂狗，分别保留/关闭可屏蔽中断 | 不执行上述监督器、CAN、ADC、FOC 或 Actor；不测运动中的功率输出关闭延迟 |

芯片 ID 检查限定器件家族 `0x468`、128KB Flash；不能凭它确定板卡型号。检查现有 `FLASH_OPTR.IWDG_SW=1`，拒绝硬件自动启动模式，不修改选项字节。

## 硬件诊断流程

1. 校验随包源码指纹、镜像哈希、固定 RAM 布局、向量表和入口，完整备份 128KB Flash 到本任务临时目录。
2. reset halt 后加载 RAM 程序，PA8/9/10、PB13/14/15 保持复位模拟模式，TIM1 CR1/CCER/BDTR 为 0。不启动 PWM。
3. 清除旧复位标志，关闭调试 IWDG 冻结，开启仅计数的 SysTick；中断中从不喂狗。
4. 软件启动 IWDG，分频 32、RLR=199、WINR=4095。以标称 LSI 32kHz 计算约 200ms；LSI 有偏差，不能作为电机保护的最坏延迟保证。
5. 前台每约 10ms 喂狗，持续 60 次、约 600ms。模式 1 停止前台喂狗但保留 SysTick；模式 2 再关闭全部可屏蔽中断。两种情况都必须触发 IWDG 复位。
6. 调试器在复位入口捕获核心，核对 PC 与原 Flash 向量表、Thread 模式和新产生的 IWDGRSTF。邮箱保留喂狗次数、周期数和中断计数；不能仅凭等待时长或旧复位标志判定通过。
7. 最终 reset halt、恢复原调试冻结设置，检查输出为 0、Flash 全量相同、选项字节未变。失败也尝试此清理，不自动重跑或恢复 Flash 应用。

## 构建和执行

路径相对 skill 根目录。使用 GNU Arm 工具链和已审计私有工程的 CMSIS 头文件，不能用 Arm Compiler 6 参数替代本入口。需要可执行的 pyOCD commander 和已核对 STLink UID。

```text
python -B scripts/test_g431_watchdog.py --compiler GCC --output NEW_TASK_TEMP_SOFTWARE
python -B scripts/g431_watchdog_pil.py build --arm-bin GNU_ARM_BIN --cmsis-root PRIVATE_FOC_ROOT/Drivers/CMSIS --output NEW_TASK_TEMP_BUILD
python -B scripts/g431_watchdog_pil.py run --build NEW_TASK_TEMP_BUILD --output NEW_TASK_TEMP_RESULT --pyocd PYOCD_EXECUTABLE --uid VERIFIED_STLINK_UID --power-stage-disconnected --reset-and-halt-ack
```

本 Windows 环境的输出必须是 `E:/simulink/_codex_tmp` 下的独立新子目录；全部原始轨迹、邮箱和私有 Flash 备份留在该目录。两个确认标志记录现有现场确认和 RAM 操作授权，不能替代物理断电。公开交付仅保留整理后的结果，避免上传私有镜像或 STLink UID。

## 监督器接入要求

- `motor_td3_health_*` 只在前台调用；ISR 只更新采样/时钟计数。前台通过短临界区取得一致快照，再提交新序号。不要让 ISR 与前台并发修改 64 位监督状态。
- 每一类 `progress` 只在对应计数确实有新进展时调用。ADC 提交必须代表完整、有效的新转换；重复旧读数或前台循环次数不算 ADC 进展。
- 仅 `may_feed` 返回真时由前台刷新 IWDG。它要求三类序号都在上次喂狗后推进；中断仍运行不能掩盖前台卡死。
- 心跳必须由协议层先校验身份、会话、CRC 和顺序，然后调用 `heartbeat_validated`。超过期限后收到新心跳仍锁存故障；重复序号和倒退时钟也拒绝。不在运行中通过 `init` 清故障或重新装载会话。
- 监督器不执行封波。接入固件须在发现故障时首先调用已验证的禁能路径，再停止喂狗，并确保复位后默认禁止启动；验证断线、前台卡死、ADC 停止和中断卡死的完整路径。
- 主机检查的 5ms/5ms/30ms/200ms 阈值仅用于故障用例；实际期限须根据目标调度、ADC、通信抖动和保护时限确定。不能把诊断约 200ms 超时直接作为过流或电机急停阈值。

## 本次结果

2026-10-11，实际板上 RAM 镜像 1160B：两种模式各先喂狗 60 次后触发 IWDG 复位；按 HSI16 标称周期估算分别约 203.67ms、203.33ms。SysTick 在停止喂狗后分别增加 204、0 次。完整 Flash 未变，核心最终暂停、输出为 0。监督器 15 项 C 检查和 6 项 Python 合同/证据检查通过。随后禁止运动 SpeedLoop 集成版已烧录，三种断电故障与真实 CAN 应用心跳停止均触发独立复位，复位后保持禁止启动。具体流程及限制见 [speedloop-watchdog.md](speedloop-watchdog.md)，运动保护时限仍待验证。

依据 ST [RM0440 独立看门狗说明](https://www.st.com/resource/en/reference_manual/dm00355726.pdf) 与目标工程内 ST HAL IWDG/CMSIS 定义：IWDG 使用独立 LSI；软件启动后需复位才能停止；调试冻结会影响验证，测试时须明确关闭。
