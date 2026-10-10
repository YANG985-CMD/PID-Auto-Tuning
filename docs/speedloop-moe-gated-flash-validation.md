# SpeedLoop 门控镜像烧录验证

2026-10-11，Codex 在用户确认 24 V 功率电源断开的条件下，把 `17.SpeedLoop` 的副本编译成 STM32G431CBUx 镜像，并通过用户板上的 ST-Link 写入 Flash。原工程目录没有被改写。

## 镜像内容

- USER3 启动路径先检查 ADC 零点完成标志和 TIM1 Break 标志。
- 启动相桥时先清 MOE，再一次性开启 CH1/2/3 及互补通道；任一步 HAL 调用失败都会回到禁能状态，最后才置 MOE。
- 停止路径关闭 MOE、停止三相及互补通道，并再次清理相位 CCER 位。
- ADC 注入采样仍由 TIM1 CH4 触发。高级定时器在该板上需要 MOE 才能保持这个触发路径，因此启动时只保留 CH4 的 CCER 位，明确清除 CH1/2/3 及互补位，再保留 MOE。这样采样可以完成，相桥通道仍关闭。

## 编译和写入证据

- GNU Arm Embedded Toolchain 14.2.rel1 在临时目录编译，文本/数据/BSS 为 `36220/136/3504` 字节，总镜像约 36 KB。
- Intel HEX 每条记录校验通过；初始栈为 `0x20008000`，复位向量为 `0x08000265`，均落在 STM32G431CBUx 有效范围。
- 使用 `Keil.STM32G4xx_DFP.2.2.0.pack` 识别目标为 `STM32G431CBUx`。写入后用 ST-Link 对 Flash 做完整二进制比较，`36356` 字节全部匹配。

## 写入后断电运行检查

24 V 仍断开、未按 USER3，复位运行约 300 ms 后暂停核心，读到：

```text
ADC_offset = 1
IA_Offset  = 2022
IB_Offset  = 2029
IC_Offset  = 2026
Motor_state = 0
TIM1->CR1  = 0x00000121
TIM1->CCER = 0x00001000   // 只有 CH4，CH1/2/3 及互补通道关闭
TIM1->BDTR = 0x0202B078   // MOE 保留给 CH4 采样触发；相位 CCER 仍全关
```

这次操作没有接通 24 V、没有按 USER3、没有启动电机，也没有发送 TD3 增益。核心在读回后保持暂停。重新接通母线前仍需完成带电流基准的过流阈值、急停/失联路径和受限试转验收；该镜像是安全门控的 SpeedLoop 基线，不是 TD3 常驻部署。
