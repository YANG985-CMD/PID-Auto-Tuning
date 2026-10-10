# STM32G431 三相电流 ADC 零点观察

2026-10-11，用户确认 24V 功率电源断开、USB/STLink 供电。Codex 在实际 STM32G431 的 SRAM 中运行独立 ADC 观察程序，采集现有三相电流通道的静态原始码。程序没有访问 CAN/串口，没有配置 TIM1 或 PWM，没有写入 Flash，也没有修改 DAC 过流门槛。

## 实测结果

| 项目 | 结果 |
|---|---|
| 诊断检查 | 7/7 通过 |
| 每相样本 | 64 个，合计 192 个 ADC 码 |
| A 相 | 均值 2021.078，范围 2019–2022，标准差 0.669 码 |
| B 相 | 均值 2028.781，范围 2027–2031，标准差 0.739 码 |
| C 相 | 均值 2024.625，范围 2023–2026，标准差 0.696 码 |
| ADC 状态 | ADC1/ADC2 均无 overrun；单端校准完成，CALFACT 读回 61/62 |
| 输出隔离 | 所有样本安全位为 1；TIM1 CR1/CCER/BDTR=0，GPIO 时钟关闭 |
| 收尾 | 核心暂停，128KB Flash 逐字节未变 |

原例程在启动时也会用 10 次注入采样得到 `IA_Offset/IB_Offset/IC_Offset`，再计算 `I=(ADC-Offset)*0.02197265625`。这次结果表明板上的静态 ADC 通道有稳定读数和很小的短时波动；它可以作为启动零点检查的证据。

## 不能从本次数据推出的结论

- 24V 断开时测到的是零电流偏置，不能代替正常母线电压、PWM 噪声和负载下的采样验证。
- 零点样本不能识别电流增益、采样电阻误差、运放增益误差或 ADC/DAC 绝对误差；还需要已知正负电流的受控校准。
- 之前比较器诊断得到的静止输入交叉码为 DAC 2033–2034；它与本次采样不是同一次同步校准。按现有标称比例做的 3000 码电流只是约 21.23–21.25 A 的算术估计，不是实测跳闸电流。
- 现有工程仍只审计到 C 相上限比较，尚未证明三相正负方向都受到硬件保护，也没有证明 MOE 从 1 自动清零或功率输出关闭延迟。

因此，本次结果**不写入任何 ADC 偏置、DAC 门槛或 TD3 参数**，也不开放真实电机动作范围。完整数据见 [summary.json](../examples/stm32g431-current-zero/summary.json)。

## 首次执行的修正

第一次执行在采样前因把 OPAMP 的出厂修调位误当作配置位而退出（错误码 0x8）。该修调位由芯片复位加载，属于正常状态；修正检查后重新构建并完成上述 7/7 测试。第一次失败不是硬件过流保护失败。

## 复现实验

```text
python -B skills/motor-td3-serial-tuning/scripts/g431_current_zero.py build --arm-bin ARM_COMPILER_BIN --cmsis-root PRIVATE_FOC_ROOT/Drivers/CMSIS --output NEW_BUILD
python -B skills/motor-td3-serial-tuning/scripts/g431_current_zero.py run --build NEW_BUILD --output NEW_RESULT --power-stage-disconnected --reset-and-halt-ack
```

流程只接受随 skill 提供的固定 SRAM 镜像；两个确认参数只记录用户已确认的断电和 SRAM 覆盖条件，不能替代物理断电。
