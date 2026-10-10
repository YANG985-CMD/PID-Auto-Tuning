# 已知电流校准流程

当前板上已有的零点观察只能得到 ADC 偏置，不能得到电流增益。资料中两个示例的换算系数也不一致：PID 工程使用 `0.02197265625 A/码`，Folder 4 的另一个示例使用 `0.0193359375 A/码`。在这两个值没有由实测电流确认前，不能把 DAC 3000 转换成安培保护值。

## 需要的条件

- 隔离、限流的已知电流源或经过校准的电流测量设备；当前已知的 24V/3A 电源本身不能提供电流测量基准。
- 明确的板级电流注入夹具或由电气工程师确认的 shunt 测试接点。不能把电流源直接接到逆变器相线或栅极节点来“试一下”。
- 电压表/示波器用于确认母线、PWM 禁能和比较器/Break 关断；温度仍需要外部测量。

## 采样格式

每行一个同步样本，使用 `phase,reference_A,adc_code`：

```text
phase,reference_A,adc_code
A,-2.0,1948
A,0.0,2048
A,2.0,2148
```

每相至少 6 个样本、3 个电流等级，建议包含正负电流和 0 A。保持电流稳定后同时记录参考电流与 ADC 原始码；不要用聊天消息中的估计电流替代仪器读数。

## 离线拟合

```text
python -B skills/motor-td3-serial-tuning/scripts/fit_current_calibration.py SAMPLES.csv --output FIT_OUTPUT
```

脚本对每相拟合 `I = gain * ADC + intercept`，输出增益、零点、R²、残差、饱和样本和正负电流覆盖情况。它始终输出 `device_write=false`、`current_gain_calibrated=false`、`current_threshold_calibrated=false`，不会打开调试器或改变 MCU。

## 通过条件

R²、残差、重复性、正负方向和热漂移的数值门限必须由目标电机/驱动器的测试计划确定。拟合结果通过后，还要单独验证 COMP1 的真实电流触发、TIM1 Break、MOE 和三相正负覆盖；不能直接用拟合增益改 DAC 或开放 TD3。
