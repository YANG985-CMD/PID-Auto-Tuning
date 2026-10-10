# SpeedLoop 的 MOE 门控复核

## ADC 触发与功率输出

用户确认可运行的 `17.SpeedLoop` 使用 TIM1 CH4 触发 ADC 注入转换。
断电运行检查中，`CCER=0x1000`（只有 CH4）、`BDTR=0x0202B078`（MOE=1）、`Motor_state=0`。
这时三相通道关闭，但 MOE 已置位；相位 CCER 位意外打开就可能允许栅极驱动。

这条 CH4 采样路径在当前板上依赖 MOE，不能简单关 MOE 后声称电流采样仍在运行。
后续的禁止运动诊断版本取消 TIM1 启动，改为 100Hz 软件触发注入采样，同时保留 MOE=0、相位 CCER=0。
软件触发是顺序 ADC 诊断，不能代替原 10kHz FOC 的同步电流反馈。

## 更正此前的启动描述

先清 MOE，然后逐个调用 `HAL_TIM_PWM_Start` / `HAL_TIMEx_PWMN_Start`，最后再次置 MOE，
**不能保证原子启动**：现有 HAL 在各次 Start 内部就会打开 MOE。
此前示例和烧录记录对这一点的描述不准确，已更正。旧镜像的失败清理和停止路径仍有作用，
但不能据此认定六路同时开启或完整安全门控已验证。

未来允许启动的版本需独立实现并验证通道配置、CCR、Break/故障锁存、采样就绪、Hall、
控制状态与最后输出使能之间的完整顺序，避免中途由 HAL 提前置 MOE。
当前诊断固件移除启动入口，USER3 只触发停止/故障锁存，CAN BEGIN/GAINS 均被拒绝。

## 调试暂停与停止

调试器暂停 CPU 不保证 TIM1 停止；GPIO/PWM 可能继续输出最后的占空比。
带电运行时必须先通过板端停机链路禁能，再确认状态，不能把调试器 halt 当作急停。
这次试转曾在 halt 后才写寄存器关闭输出；已记录为流程缺口，后续运行须有独立、限时停机与连续遥测。

24V 断开后完成复位清理，读回 `Motor_state=0`、MOE=0、CCER=0、CEN=0，核心保持暂停。
详见 [单次试转与停机复核](speedloop-trial-and-stop-review.md) 和 [历史镜像烧录记录](speedloop-moe-gated-flash-validation.md)。
