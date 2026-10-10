# SpeedLoop 前台监督与独立看门狗集成

这是禁止运动的诊断版本 `g431-speedloop-wdog-v1`，通过 `build_speedloop_diagnostic.py --watchdog` 创建。原私有工程不修改；能力位为 0，链接中不得出现 PWM 启动、FOC step 或模糊 PI 执行入口。它不是生产运动固件。

## 实现

- 约 100Hz 软件 ADC 发布完整转换计数；前台取一致快照，只有主循环、时钟和 ADC 都有新进展才刷新 IWDG。ISR 不喂狗。
- 在 IWDG 寄存器同步完成后开始计算健康期限，避免将初始化等待误判为主循环超时。
- HELLO 建立会话后启用 200ms 心跳期限；仅 CRC、会话、启动身份和顺序校验通过的 STOP 命令刷新心跳。STOP 只保持禁能；它不是运动租约实现。
- 协议异常有独立锁存标志，不让默认 NOT_READY 故障掩盖错误心跳。晚到的采样或报文不能清故障。
- 发现故障先禁能，再停止喂狗。IWDG 复位后在 HAL/外设初始化前检查复位原因，保持禁止启动。
- CAN 一次只保留一个待发送帧，以匹配 marker、ID、格式的 Tx Event 确认实际发送完成，超时锁存。前台等待非阻塞；不靠降低丢帧检查标准通过测试。
- 此版本开启 CAN 硬件自动重传，并用 50ms 发送期限约束它。原例程关闭自动重传（DAR），仲裁失败后报文会被取消；成功发送的事件类型也为 ET=10。新增事件检查最初误拒绝了这种合法事件，已通过改用有自动重传的配置修正；本版本正常事件为 ET=01。
- 5ms 主循环/时钟、30ms ADC、200ms 心跳和标称约 200ms IWDG 都是诊断设定，未验证运动保护最坏延迟。

## 执行流程

已有用户授权和供电确认可复用；标志不能代替现场状态。

1. 功率电源物理断开时构建、完整回读并运行断电测试，保留私有恢复镜像在任务临时目录。
2. `speedloop_watchdog_validate.py` 先检查芯片、Flash、软件 IWDG 选项和输出禁能，再 reset halt 后烧录。测试健康运行、ADC 停止、前台停滞和可屏蔽中断关闭，捕获新 IWDG 复位原因及复位后禁能状态。
3. `speedloop_watchdog_can.py prepare` 仅在功率断开时初始化已核验固件、暂停并冻结 IWDG，写入一次性诊断 boot token。
4. 现场确认板端供电后执行 `run`；两次完整镜像回读都须一致。仅发一次 HELLO 与有序 STOP，保持 PCAN 正常 ACK；随后停止应用层心跳，观察故障、IWDG 复位和复位后锁定。没有物理拔线。
5. 故障不自动重启、重装会话或重发握手。结束先暂停已经核验的禁止运动固件并确认输出关闭，再释放 PCAN。
6. 重新准备、复位或烧录前要求物理断开功率电源。诊断中观察到禁能寄存器不等于运动中的电流衰减或功率输出关闭延迟验收。

```text
python -B scripts/test_g431_integration.py --watchdog --compiler GCC --output NEW_TEMP_HOST
python -B scripts/test_speedloop_watchdog_validate.py
python -B scripts/build_speedloop_diagnostic.py --watchdog --source PRIVATE_SPEEDLOOP_ROOT --arm-bin GNU_ARM_BIN --output NEW_TEMP_BUILD
python -B scripts/speedloop_watchdog_validate.py --build NEW_TEMP_BUILD --output NEW_TEMP_RESULT --pyocd PYOCD --uid VERIFIED_UID --pack VERIFIED_PACK --power-stage-disconnected --reset-and-halt-ack
python -B scripts/speedloop_watchdog_can.py prepare --build NEW_TEMP_BUILD --output NEW_TEMP_PREPARE --pyocd PYOCD --uid VERIFIED_UID --power-stage-disconnected
python -B scripts/speedloop_watchdog_can.py run --session NEW_TEMP_PREPARE/session-private.json --output NEW_TEMP_CAN --allow-live --board-power-confirmed
```

本机临时目录为 `E:/simulink/_codex_tmp`。烧录入口固定审核过的镜像 SHA、尺寸和源码指纹；修改后先重新构建、审核，再更新允许的版本。不要改成接受任意镜像。

## 限制

测试选择器仅供断电诊断调试器注入，不通过 CAN 暴露。正式运动版本应移除它，并重新验证保护时限、启动/禁能、实时调度和故障恢复。

当前数据仍是四帧原始诊断，缺少原子动作应用回读和训练观测。温度、外部电流标定、实体急停、运动中的独立停机及真实基准仍是实机 TD3 门槛；通过看门狗诊断不允许解除它们。

依据 [ST RM0440](https://www.st.com/resource/en/reference_manual/dm00355726.pdf)、[ST G4 HAL FDCAN 源码](https://github.com/STMicroelectronics/stm32g4xx-hal-driver/blob/master/Src/stm32g4xx_hal_fdcan.c) 和 [ST AN5348](https://www.st.com/content/st_com/en/technical-documents/an5348-introduction-to-fdcan-peripherals-for-stm32-mcus-stmicroelectronics.html)。Tx FIFO 的入队成功与实际发送完成是不同阶段；本版本以发送事件确认后者。
