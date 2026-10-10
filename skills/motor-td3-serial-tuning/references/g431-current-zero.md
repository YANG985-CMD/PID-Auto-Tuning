# G431 静态电流 ADC 零点观察

在已核对的 STM32G431/H17 电机板上，功率电源物理断开、只保留 USB/STLink 时，可运行 `scripts/g431_current_zero.py`。它使用固定 SRAM 镜像读取三相电流通道的原始 ADC 码，检查 ADC 单端校准、采样配置和短时波动。若要检查 24V 带电但 PWM 禁止时的零点漂移，使用 `--power-stage-connected --pwm-disabled-ack`；该模式仍只运行 SRAM 诊断，不恢复 Flash 应用。

## 范围

- 不开 CAN/串口，不启用 TIM1、PWM 或相位复用，不写 Flash，不写 ADC 偏置、DAC 门槛或 TD3 参数。
- 带电模式需要用户确认 24V 已接通且 PWM 保持禁能；运行器会在复位后再次检查 TIM1/功率引脚状态，不能用确认标志代替寄存器检查。
- 24V 断开时的结果是零电流偏置观察，不等于带母线和 PWM 时的噪声，也不等于过流跳闸电流。
- `nominal_plan` 只使用已完成的零点与比较器诊断报告做算术展示，始终返回 `device_write=false`、`current_gain_calibrated=false`、`current_threshold_calibrated=false`。
- 得到已知电流增益需要受控正负电流源或经测量的负载；不能从零点单独推断 A/count。

## 结果判定

必须有 7/7 检查、每相 64 个样本、无 ADC overrun、无 ADC rail、所有样本安全位、TIM1/相位 GPIO 关闭、完整 Flash 未变和最终核心暂停。OPAMP 的出厂修调位是复位状态，不能把 `TRIMOFFSETN/P` 或只读 `OUTCAL` 状态误判为路由配置。

## 资料依据

原例程在启动注入转换回调中用 10 次样本形成 `IA_Offset`、`IB_Offset`、`IC_Offset`，随后按 `0.02197265625 A/count` 换算。这个比例来自板级标称电阻/放大器/ADC 假设，不是本诊断重新标定的结果。STM32G4 ADC 需要先启用模拟稳压器并完成单端校准；ST 的 RM0440 和 HAL/LL 资料描述了该顺序以及 OPAMP 出厂修调位的含义。

## 已完成结果

见 [STM32G431 电流 ADC 零点报告](../../docs/stm32g431-current-zero-validation.md) 和 [机器可读摘要](../../examples/stm32g431-current-zero/summary.json)。
