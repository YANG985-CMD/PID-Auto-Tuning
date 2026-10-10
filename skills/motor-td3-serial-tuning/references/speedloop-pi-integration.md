# 17.SpeedLoop：真实速度 PI 参数接入

## 当前实现

用户指定正常运行的 `17.SpeedLoop` 为工程基准。本版本从实际 Keil 工程引用的 `MATLAB/FOC_Model.c` 接入；不修改用户原工程，不上传厂家代码。

| 项目 | 原工程值与处理 |
|---|---|
| 基础 Kp / Ki | `0.003389 / 0.00144` |
| 电流 / 速度任务 | 名义 `100µs / 1ms`；速度任务由生成代码每 10 次调用执行 |
| Ki | 连续积分增益；模型在上一输入积分时乘 `0.001s`，外部接口不再乘一次周期 |
| 电流换算 | `(raw - dynamic_offset) × 0.02197265625 A/count`，采用例程名义系数 |
| 零点 | 保留启动 10 次采样平均；不硬编码外部参考偏置 |
| Iq 指令限幅 | 保留 `±3`，不是独立测得的相电流跳闸值 |
| 比较器 | 保留 PB1 / DAC3 CH1、DAC 码 `3000`、TIM1 Break 高有效、滤波 2、自动重启禁用 |
| 热信息 | 没有实际测温与已验证热限值；保留缺失状态 |

例程的模糊控制器在每次电流采样回调中写 `spd_kpki`，因此直接下发 TD3 增益会被覆盖。`motor_td3_speedloop_pi_fast()` 只在默认模糊模式继续这些写入；外部模式提交后保持单一参数所有者。

## 提交与积分连续性

1. 已通过外层保护的调用者使用 `motor_td3_speedloop_pi_queue()` 提交完整增益对、单调动作序号与设备绝对期限。板级 facade 保存并恢复 PRIMASK，串行化前台队列与 ADC 控制任务。
2. 真正的 1ms PI 任务先按生成代码完成上一输入的积分和 reset，再调用绑定层。暂存不算应用，reset 优先并推迟参数提交。
3. 为保持切换瞬间的 PI 输出，使用 `I_new = I_old + (Kp_old - Kp_new) × error`。积分状态已经是输出量，不按 Ki 比例缩放。原 `±3` 饱和与条件抗积分饱和保持不变。
4. 成功提交后记录实际 `Kp/Ki`、应用序号、应用设备时间、积分状态以及切换前后和。未来 CAN 必须回传这一结果，不能把“已收到队列”当应用确认。
5. 拒绝非法增益、NaN/Inf、重复序号、覆盖尚未提交的动作、期限到达、非单调时钟和外部模式的其他写入者。任何失败锁存故障；绑定层清 MOE/CCER 和软件启动标志，实际模型立即返回。

暂存动作与当前动作保留**不同期限**。排队新动作或 reset 不能延长已生效动作的期限。

模糊规则的数学范围约为 Kp `[0.0013556, 0.0054224]`、Ki `[0.00072, 0.00216]`，当前绑定层使用对应 float32 边界做输入检查。任意 TD3 轨迹处于这个范围不等于稳定，尚无获准的实机探索范围或步长。

设备时钟使用 DWT CYCCNT，并在每次 PI 边界延伸到 64 位微秒。160MHz 下约 26.84 秒回绕一次；必须持续服务才能识别回绕。控制任务停止时，这个边界检查不会运行，不能代替独立进展监督、IWDG 或急停。既有诊断看门狗的板上通过不能自动当作本次运动实现的验收。

## 离线复现

公共模块检查，不需要厂家工程：

```text
python -B skills/motor-td3-serial-tuning/scripts/test_speedloop_pi.py --output TASK_TEMP_PI --compiler gcc
```

私有工程集成检查与完整 Cortex-M4 编译：

```text
python -B skills/motor-td3-serial-tuning/scripts/build_speedloop_pi_integration.py --source PRIVATE_17_SPEEDLOOP_TEMPLATE --output TASK_TEMP_INTEGRATION --compiler HOST_GCC --arm-bin ARM_GNU_BIN
```

输出使用新的空目录；Windows 必须位于 `E:/simulink/_codex_tmp/`。构建器严格核对原始源树、生成模型和 42 个 Keil 单元，自动补丁私有副本，加上两个模块形成 44 单元工程。未知版本应先审计，不能去掉哈希检查强行套用。

`summary.json` 区分核心检查、真实生成模型检查、基准轨迹和工程编译。主机模型测试使用合成观测，不是电机或逆变器仿真。2000 步基准轨迹验证默认模糊模式的数值一致性，不验证闭环性能。

## 当前副本与下一接口

复核副本身份 `g431-speedloop-pi-review-v1`，保留实际 FOC 与 CH4 采样代码，移除相桥启动调用；USER3 仅停机。它不是之前约 100Hz 软件 ADC 诊断版本，也不是已批准运动镜像。此入口没有下载、复位、CAN 或串口功能；现有固定硬件入口继续拒绝不同镜像。

默认 PI 复核构建仍不启用 CAN。新增 `--can-pi` 把现有 CAN 端点和 G431 HAL 端口接到同一 PI 边界：RX 只排队，在 reset 就绪后由 `motor_td3_speedloop_can` 同步提交并核对实际增益；正式反馈使用边界应用时间。STOP 和期限检查不因 reset 延后。内部 PI 用 wire 序号，正式协议仍用动作 command_seq，二者不混用。

该选项同时统一 DWT 时间轴、中断串行化与单一 CAN 命令所有者，复用已有 Rx 队列和单帧 Tx 事件检查。主机用现有 Python 编码器和用户真实模型跑通 10 项接入检查；19 项公共 CAN 回归通过。完整构建为 49 单元，身份 `g431-speedloop-pi-can-review-v1`，能力仍为 0、相桥启动移除，没有烧录或重测物理 CAN。缺失温度不会编码为训练遥测。

锁定适配层仍关闭 MOE，连同 CH4 采样触发一起停止；当前是编译复核副本。运行固件的持续采样、启动门控、独立进展/停机保护、热能力和 Actor 仍待接入同一实现。既有物理 CAN 结果无需作为前置工作反复重测；新运行镜像须验证自己的实际行为。构建不改变板上 Flash，也不把名义电流转换为实测校准标记。

```text
python -B skills/motor-td3-serial-tuning/scripts/build_speedloop_pi_integration.py --can-pi --source PRIVATE_17_SPEEDLOOP_TEMPLATE --output TASK_TEMP_CAN_PI --compiler HOST_GCC --arm-bin ARM_GNU_BIN
```

Simulink 再生成可能覆盖模型补丁。构建器每次从指定原工程重新生成补丁副本，不在生成代码目录留下隐含修改。
