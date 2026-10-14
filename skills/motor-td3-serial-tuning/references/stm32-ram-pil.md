# STM32 Actor 的 RAM 部署与 PIL

此入口用于验证“MATLAB 训练出的网络，能否在 MCU 上正确计算”。Codex 导出小型 Actor，调用目标编译器，经 STLink 把计算镜像放入 SRAM，执行测试输入并读取结果，再分析数值、周期和栈占用。训练仍在 MATLAB；MCU 仅执行 Actor。

已在 STM32G431 上验证。[实测记录](evidence/stm32g431-validation.md) 包含结果和范围。

## 条件与实际影响

- 仅支持器件 ID `0x468`、Cortex-M4、128KB Flash 的 STM32G431/G441 目标；无法由 ID 区分封装，须同时核对原理图/实物。只允许连接一个调试器。
- **先物理断开电机功率电源，确认控制部分仍有供电。**降低给定、软件停机或适配器标称电流不能替代断开。运行入口需取得这项现场确认。
- 测试会暂停原应用、执行系统复位、覆盖前 20KB SRAM，并将计算镜像加载进 RAM。它不是被动监视，不能用于正在运行的电机。
- 系统复位后检查 TIM1 输出使能关闭，才加载网络。不启用 GPIO、UART、PWM，不下发电机命令或应用 Kp/Ki。
- 启用 FPU 和 DWT 周期计数器，屏蔽中断；正常完成通过 `BKPT` 暂停。异常/超时同样尝试保持暂停，报告实际结果。
- 不使用 Flash 擦写接口；测试前备份完整 128KB Flash，测试后逐字节比较。备份包含私有固件，只存指定的本地任务目录，不上传。
- **结束保持核心暂停，不能自动恢复原电机应用。**复位或断电重启会重新执行原 Flash 固件；恢复供电与运动必须按该固件的启动和保护流程进行。

此步骤可以对模拟 Actor 做计算验证，因为输出不接电机。`simulation_only` 与 `hardware_deployment_approved=false` 仍保留；PIL 通过不能解除实机调参门槛。

## 工具与命令

需要 Arm Compiler 6（`armclang`/`armlink`，本次为 6.9）、pyOCD 0.45.1 和 libusb-package。依赖见 `scripts/requirements-pil.txt`；遵循本机临时目录规范安装/构建，不在用户源工程生成中间产物。

以下路径是占位参数。`BUILD_OUTPUT` 和 `RUN_OUTPUT` 都应为指定临时目录下新的空目录。构建不访问调试器：

```text
python -B scripts/stm32_actor_pil.py build --model ACTOR_JSON --reference MATLAB_REFERENCE_JSON --arm-bin ARM_COMPILER_BIN --output BUILD_OUTPUT
```

最多 40 组参考输入。构建从 Actor JSON 重新生成算术 C，拒绝异常数值/结构，不接受外部 C 文件作为网络代码；ELF 的加载段和入口必须全部在保留的 SRAM 区域。使用 Cortex-M4F 单精度硬浮点，关闭浮点融合和 fast-math。

已明确确认功率电源断开，并接受复位/SRAM 替换后，在已授权的试板会话中执行：

```text
python -B scripts/stm32_actor_pil.py run --build BUILD_OUTPUT --output RUN_OUTPUT --power-stage-disconnected --reset-and-halt-ack
```

标志只记录已完成的现场确认，不能证明电源状态。禁止为使脚本运行而代替用户假定已断开。

只读身份入口使用 attach，不复位、不加载镜像、不打开串口：

```text
python -B scripts/stm32_actor_pil.py probe --output PROBE_OUTPUT
```

## 结果判定

`pil-result.json` 需要同时满足：完成标志与向量数正确；动作误差 ≤ `2e-6`、增益误差 ≤ `2e-9`；NaN/Inf/越界增益被拒绝；栈底保护字节完整；核心最终暂停；TIM1 输出关闭；Flash 内容未变。失败不重试电机运动或自动写回 Flash。

周期数来自 RAM、复位默认时钟、屏蔽中断的计算测试。40 个输入的最大观测值不代表生产固件的最坏执行时间；栈涂色最大观测值也不代表所有输入和中断嵌套的最坏栈深度。正式接入 FOC 后重新测量实时预算。

`actor-pil.bin` 包含测试向量和数学库，不能作为电机控制固件烧录。永久部署须将 `motor_actor.c/.h` 接入已验证的固件任务、观测输入、参数映射和独立保护，按 [firmware-integration.md](firmware-integration.md) 完成验收。

## 调试依据

- [pyOCD 调试器支持](https://pyocd.io/docs/debug_probes.html)
- [pyOCD 会话选项](https://pyocd.io/docs/options.html)：attach、禁止自动解锁/擦除、禁止断开后自动运行。
- 芯片与寄存器映射同时依据本地 STM32G4 DFP/CMSIS、板卡原理图核对。
