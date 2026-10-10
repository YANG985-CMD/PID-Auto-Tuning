# SpeedLoop 启动校零回读

当前板上能正常运行的基准工程是：

`Folder 2 Program Model/17.SpeedLoop/5.SpeedLoop/BLDC_Speedloop_code/STM32G4_FOC_template`

它在启动时先用 10 次注入 ADC 样本形成 `IA_Offset`、`IB_Offset`、`IC_Offset`，再等待 USER3
开启三相功率 PWM。A/B/C 的断电静态参考均值是 `2021.08/2028.78/2024.63` 码。工程变量是
`uint16_t`，所以启动时通常看到 `2021/2029/2025`；参考值用于发现异常，不能替换动态校零。

仓库中的 `skills/motor-td3-serial-tuning/scripts/read_speedloop_ram.py` 提供两种模式：

```text
python -B skills/motor-td3-serial-tuning/scripts/read_speedloop_ram.py map \
  --map "E:\\dianji\\Folder 2 Program Model\\17.SpeedLoop\\5.SpeedLoop\\BLDC_Speedloop_code\\STM32G4_FOC_template\\MDK-ARM\\STM32G4_GPIO\\STM32G4_GPIO.map"
```

`map` 只解析私有 Keil map，不连接板子。`read` 才会通过 STLink 短暂暂停核心，读取偏置完成标志、
三相偏置和当前 `Ia/Ib/Ic/Vbus/HallSpeed`，不复位、不写 SRAM/Flash、不写增益、不发 CAN/串口命令。
它必须显式提供 `--power-stage-disconnected --reset-and-halt-ack`，默认读取后保持核心暂停；这两个选项
不是软件形式上的安全证明，而是防止误操作的现场门槛。输出应写入 `E:\\simulink\\_codex_tmp\\` 下的
独立任务目录，不要把 map、AXF 或原始回读上传到公开仓库。

回读结果解释：

- `adc_offset_complete=1` 且三相偏置分别接近 `2021/2029/2025`：启动校零路径已完成，仍不能推出安培增益。
- 偏置明显偏离、完成标志为 0 或三相电流不是接近零：停止进入 TD3 采集，先检查采样时序、PWM 状态和运放输出。
- 断电静态偏置只说明零点；过流门槛仍需已知正负电流、实测分流信号和独立 Break 验证。

## 本次板上回读

在用户确认 24 V 物理断开、USB/STLink 保持连接后，先复位运行约 300 ms 让 SpeedLoop 完成启动校零，
再暂停核心读取 RAM。结果为：

| 项目 | 回读值 |
|---|---:|
| `Motor_state` | `0` |
| `ADC_offset` | `1`（完成） |
| A/B/C 偏置 | `2023 / 2028 / 2026` 码 |
| A/B/C 与参考均值的差 | `+1.92 / -0.78 / +1.37` 码 |
| `Ia/Ib/Ic` | 各约 `0.02197 A` |
| TIM1 `CCER` | `0x00001000`，仅 CH4 触发 |
| TIM1 `BDTR.MOE` | `1` |

偏置在设定的 4 码容差内，说明这份 SpeedLoop 的动态校零路径可以作为 TD3 采集的前置检查。
相位 CH1/2/3 仍关闭，因此这次没有相位 PWM 输出；但 `BDTR.MOE` 已置位，说明工程依赖 CCER 门控保证相位关闭。
正式接入前应在启动门控中显式清 MOE，并在确认三相启动条件后再置位，减少后续改动或异常状态下的风险。

机器可读记录见 [`examples/stm32g431-speedloop-offset/summary.json`](../examples/stm32g431-speedloop-offset/summary.json)。

Codex 后续可以把这份回读作为实验日志的前置证据，再把实际生效的动作、Hall/速度、电流和故障序号送入
TD3 经验。它不会把“读取到了 RAM”解释成“策略已经可以接管电机”。
