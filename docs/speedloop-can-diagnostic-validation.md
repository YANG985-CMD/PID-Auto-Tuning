# SpeedLoop CAN 诊断固件：实际烧录与断电验证

2026-10-11，用户确认 24V 功率电源物理断开、USB/ST-Link 保持连接后，
Codex 对用户可运行的 `17.SpeedLoop` 创建私有副本、编译并写入实际 G431 板。
本次运行完整 HAL/外设初始化与诊断固件，未运行 FOC 步进、TD3 Actor 或电机。

## 构建和下载

| 项目 | 结果 |
|---|---|
| 原工程 | 1064 个 C/H/汇编/项目文件前后哈希一致 |
| 编译 | GNU Arm 14.2.Rel1；42 个原始单元 + 5 个接入单元，共 47 个 |
| ROM | text 32776B + data 20B；二进制 32796B |
| RAM | data 20B + BSS 7936B；BSS 包含 4KB 栈和 512B 堆预留，不是测得的栈峰值 |
| 启动向量 | SP=`0x20008000`，Reset=`0x080001D9` |
| 功率/控制入口 | 最终链接没有 `HAL_TIM_PWM_Start`、`HAL_TIMEx_PWMN_Start`、`HAL_TIM_Base_Start`、`FOC_Model_step`、`FuzzyPID_Compute` |
| 下载 | 原项目的 G431 128KB/32KB 目标配置；Flash 的 32796B 完整比较一致，结束再次比较一致 |

二进制 SHA256：`f4bede2fb31b59abefdded1d59c5d3b623c97bd77c6f5e905856be63e46ad23d`。
Keil pack 的 `stm32g431cbux` 是工具目标选择，不能独立证明实物封装。

原工程没有被改写。上一版完整 128KB Flash 和此次可烧录 HEX 留在本地正式交付目录
`E:/dianji/motor-td3-board-builds/speedloop-diagnostic-20261011`，私有镜像和源码不上传公开仓库。

## PWM 禁止时的采样

两段各约 300ms 的断电运行窗口取得：

| 观察 | 第一次 | 第二次 |
|---|---:|---:|
| 有效采样计数 | 30 | 60 |
| 设备毫秒时钟 | 301 | 602 |
| 采样错误 / irq_fault | 0 / 0 | 0 / 0 |
| ADC 校零标志 | 1 | 1 |
| A/B/C 偏置 | 2022/2029/2026 | 2022/2029/2026 |
| Motor_state / HallSpeed | 0 / 0 | 0 / 0 |
| Kp/Ki 存储值 | 0.003389/0.00144 | 0.003389/0.00144 |
| TIM1 CR1 / CCER / BDTR | `0x120 / 0 / 0x02023078` | 相同 |

MOE=0、相位使能=0、CEN=0 时，完整 ADC 序列仍持续完成；这验证了软件触发不依赖 CH4。
设备时间间隔 301ms 增加 30 次采样，符合约 100Hz 的诊断频率。
两个 ADC 顺序启动，未与 PWM 同步，不能替代 10kHz FOC 电流环采样。

断电时母线 ADC 原始码为 78/77，按原例程比例显示约 1.634/1.613V；
此读数没有独立电压校准，不能作为电源已物理断开的证明。断电状态来自用户的明确确认。
电流值也只采用原标称比例，不代表增益/过流安培门槛已验收。

## 无前台程序时的 SysTick 禁能

仅在 24V 物理断开的条件下，把 PC 指向 SRAM 的无限循环，不执行前台、ADC 或 CAN 处理。
TIM1 计数器始终关闭；调试器临时设置 MOE 和相位 CCER，作为禁能函数的寄存器试验：

```text
试验前：CCER=0x1555，BDTR=0x0202B078
约22个设备毫秒后：CCER=0x1000，BDTR=0x02023078，CEN=0
irq_fault=1；ADC 完成计数保持60，没有新的采样
```

这证明完整诊断固件的 SysTick 能在前台停止时清除 MOE/相位使能并锁存超时。
保留的 CH4 位没有 MOE/CEN，不产生此诊断版的 ADC 触发。
这不是独立硬件看门狗验收，也没有测量功率器件封波延迟；调试暂停或屏蔽全部中断仍会停止 SysTick。

## PC13 软件中断停机路径

复位后的 `irq_fault=0`，通过 EXTI SWIER1 触发 PC13 中断，约 22ms 后读到：
`irq_fault=1`、`Motor_state=0`、MOE=0、CCER=0、CEN=0。
验证了 USER3 对应的软件中断链路只停止并锁存故障；**没有验证实体按键/接线的急停可靠性**。

## 收尾与剩余工作

断电复位清理后：采样30次、错误0、irq_fault=0、Motor_state=0，
偏置为 2020/2030/2026；每次启动重新校零，所以与前一个窗口存在少量码差。
最终 `CR1=0x120、CCER=0、BDTR=0x02023078`，核心保持暂停。

本版固件能力位恒为0、温度缺失为NaN、CAN启动/增益命令拒绝，未部署 TD3 Actor。
SpeedLoop 状态适配与入口检查 25 项、采样故障与数值检查 7 项通过；旧适配层 25 项回归通过。
此固件的外部 CAN 握手与连续诊断帧尚未实测；此前独立 RAM CAN 16/16 的结果不能替代它。
下一步核验新固件的 CAN 持续遥测，再继续完善独立停机、热保护、电流标定与增益切换。

Codex 已完成实际编译烧录、结果解读、故障路径分析和证据整理。
TD3 的训练效果仍由独立工况比较决定，Actor 的运行/烧录能力与闭环性能分开记录。

[机器可读结果](../examples/stm32g431-speedloop-diagnostic/summary.json) ·
[可复用构建与验证流程](../skills/motor-td3-serial-tuning/references/speedloop-diagnostic.md)
