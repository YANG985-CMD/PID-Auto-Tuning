# 当前 STM32G4 原固件的只读遥测

板上现有 `17.PID control speed` 固件在 USART3（PB10/PB11）以 **921600 8N1** 发送 24 字节二进制数据。每个包的布局是：

```text
float32 ia
float32 hall_period_ticks
float32 hall_theta_rad
float32 speed_ref_rpm
float32 hall_speed_rpm
uint8   reserved[2] = 0, 0
uint8   tail[2]     = 0x80, 0x7f
```

变量名 `HallTemp` 在旧代码中实际保存的是 TIM4 Hall 捕获周期，不能当作温度使用。这个旧包没有母线电压、三相完整电流、故障码、应用序号、租约或当前实际 Kp/Ki，因此不能直接作为 TD3 训练经验的完整状态。

## 只读捕获

```text
python -B scripts/legacy_hall_monitor.py --port COMx --duration 10 --output legacy.jsonl
```

脚本只打开端口并读取数据，不发送任何字节，不启动电机，也不能写入增益。它适合在改固件前验证 PB10/PB11、波特率和数据连续性。

## 与 TD3 的关系

当前固件没有串口启动、停止或增益命令，电机由 USER3/PC13 按键控制。因此这条链路只能做 shadow 观测和离线分析，不能宣称已完成 TD3 实机训练。要进入受限实机训练，仍需在 MCU 内加入带 CRC、序号、应用回读、动作租约、失联停机和故障锁存的协议，并让三相 PWM 禁能由已验证的 MCU 停机函数实际执行。

