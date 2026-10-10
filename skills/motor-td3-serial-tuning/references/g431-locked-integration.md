# G431 FOC / CAN 锁定接入

`scripts/build_g431_locked_foc.py` 对已审计的 G431 PID-speed 例程创建私有副本，加入锁定的 CAN 适配层并完整链接。只读原源码，无下载器、串口、CAN 或 Flash 操作。源码指纹不符时停止，先审计差异。

```text
python -B scripts/build_g431_locked_foc.py --source PRIVATE_FOC_ROOT --arm-bin ARM_COMPILER_BIN --output NEW_TASK_TEMP_BUILD
python -B scripts/test_g431_integration.py --compiler gcc --output NEW_TASK_TEMP_HOST_TEST
```

路径相对本 skill 根目录。`PRIVATE_FOC_ROOT` 包含 Core、Drivers、MATLAB 和 MDK-ARM。输出必须为空且独立于源目录，按用户指定临时目录规则放置。Windows 使用 Arm Compiler 6 的 armclang/armasm/armlink/fromelf；HEX 和私有副本不能上传公开仓库。本版本未提供烧录命令。

## 固件行为

`motor_td3_g431_adapter.c/.h`：实际 FDCAN 过滤器、有限 RX/TX 缓冲、64 位毫秒扩展计时、SysTick 禁能、真实 PI/相位输出快照、诊断原始观测，以及 USER3/异常/比较器/刹车的停机接入。

`motor_td3_g431_off.h`：与 RAM 测试共享的真实 TIM1 禁能函数。先清 MOE，再清六路相位输出使能，不开启引脚或输出。

`motor_td3_can_control_init_locked`：无需虚构实机边界，能力为 0，初始故障为 `TD3_CAN_NOT_READY=12`；只提供诊断握手和 STOP，BEGIN/GAINS 不可到达板级应用回调。温度缺失保留 NaN，编码器拒绝生成训练遥测。

接入版本没有解除运动禁令的开关。生产模式必须另外完成实际门槛与板级 begin/apply 实现；不要通过修改 capability 或删除故障绕过。

boot token 由断电后的调试会话一次性提供，本版本不实现生产启动身份。诊断标准 ID：620 请求、621 分片握手；622 schema/fault/flags/Hall/ADC年龄，623 实际 Kp/Ki，624 母线/最大绝对相电流，625 Hall转速/积分输出。诊断数据不是训练经验。

SysTick 每 1ms 禁能，并读取 TIM1 的 BIF/B2IF/SBIF，将硬件 Break 证据锁存到适配层故障，即使相应 IRQ callback 未启用也能发现；不会自动清标志或故障。主循环 5ms 无进度锁存。硬件 COMP1/TIM1 刹车配置保留，实际电流门槛仍待验证。SysTick 不能证明全局关中断或 MCU 卡死时也可停机，需独立硬件看门狗/刹车验收。

## 断电 RAM 验证

```text
python -B scripts/g431_locked_pil.py build --arm-bin ARM_COMPILER_BIN --cmsis-root PRIVATE_FOC_ROOT/Drivers/CMSIS --output NEW_TASK_TEMP_PIL_BUILD
python -B scripts/g431_locked_pil.py run --build NEW_TASK_TEMP_PIL_BUILD --output NEW_TASK_TEMP_PIL_RESULT --power-stage-disconnected --reset-and-halt-ack
```

两个确认参数代表已有会话授权和现场确认，禁止未经确认直接加入。用户已经确认电机功率电源断开，且授权继续这些验证时不重复询问。

运行入口只允许单个 STLink、已核对的 G431/G441 128KB 身份和专用 SRAM 布局。不访问 CAN 适配器、不运行原 Flash 程序，最后复位并暂停、确认 TIM1/GPIO 关闭、比较完整 Flash；失败同样尝试这些收尾步骤。

测试执行共享禁能函数、锁定协议端点和实际 SysTick。它没有执行完整 HAL/FOC 接入固件；观测和参数是测试夹具，不声称已经验证真实增益切换、过流阈值或 TD3 实机训练。

2026-10-10：完整构建 45 单元成功；板级软件 16/16、RAM 入口校验 5/5；真实 MCU 测试 11/11，55 次 SysTick、71 次禁能调用，栈观测 872 字节，Flash 未变。能力保持 0，真实训练门槛未解除。

2026-10-11：新增硬件 Break 标志轮询，实际适配层软件测试增至 19/19，加上 RAM 入口 5/5，共 24/24；完整 45 单元重建成功（ROM 44,768 B、RAM 8,176 B），仍未运行完整 FOC 固件。独立 SRAM 的 [COMP1/Break 信号测试](g431-comp-break.md) 8/8 通过；不把该独立程序的故障锁存当成完整适配层的板上执行证据。
