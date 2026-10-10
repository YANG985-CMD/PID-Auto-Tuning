# SpeedLoop 的 MOE 门控检查

## 现象

用户确认可运行的 `17.SpeedLoop` 工程启动后需要 `TIM1 CH4` 产生 ADC 触发。
`HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_4)` 会使高级定时器的主输出使能（`BDTR.MOE`）置位。
这次在 24 V 断开、复位运行 300 ms 后读取到：

```text
Motor_state = 0
TIM1->CCER = 0x00001000    // 只有 CH4，CH1/2/3 及互补通道均关闭
TIM1->BDTR = 0x0202B078    // MOE=1，Break 配置仍在
```

因此当前没有相位 PWM 输出，但安全性依赖相位 CCER 一直保持关闭。只要后续代码、异常路径或调试操作意外
打开 CH1/2/3，MOE 已经允许主输出，可能在母线接通时产生栅极驱动。`Motor_state=0` 不是硬件急停，
`BDTR.MOE=1` 也不应作为“电机可以安全上电”的证明。

## 建议的源代码改动（仅用于私有副本）

在启动 ADC 的 CH4 后立即显式关闭 MOE：

```c
HAL_TIM_Base_Start(&htim1);
HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_4);
__HAL_TIM_MOE_DISABLE(&htim1);
```

把 USER3 的启动路径改为“先关闭 MOE、再一次性打开三相通道、最后打开 MOE”，并在停止路径的最后再次关闭：

```c
static void MotorPwmDisable(void)
{
    __HAL_TIM_MOE_DISABLE(&htim1);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_1);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_2);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_3);
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_1);
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_2);
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_3);
    TIM1->CCER &= ~(TIM_CCER_CC1E | TIM_CCER_CC2E | TIM_CCER_CC3E |
                    TIM_CCER_CC1NE | TIM_CCER_CC2NE | TIM_CCER_CC3NE);
    __HAL_TIM_MOE_DISABLE(&htim1);
}

static void MotorPwmEnable(void)
{
    __HAL_TIM_MOE_DISABLE(&htim1);
    /* Check fault latch, ADC offset completion and valid Hall state here. */
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_3);
    HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_1);
    HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_2);
    HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_3);
    __HAL_TIM_MOE_ENABLE(&htim1);
}
```

实际接入时还需要把比较器 Break、故障锁存、失联租约和 USER3 停机统一调用 `MotorPwmDisable()`。
这段代码没有写入用户工程；在复制工程中编译后，先用 24 V 断开检查 `MOE=0`，再做任何带母线试验。

## TD3 门槛

在 MOE 门控、过流电流增益和停机路径没有完成编译及断电验证前，TD3 只能做离线或 shadow 预测，不能发送
改变 `Kp/Ki` 或启动电机的命令。校零回读通过只说明 ADC 零点正常，不解除这个门槛。
