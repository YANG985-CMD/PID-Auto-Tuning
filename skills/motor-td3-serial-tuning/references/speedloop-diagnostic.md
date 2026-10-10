# SpeedLoop 禁止运动的 CAN 诊断

适用输入：用户确认可运行的 `17.SpeedLoop/5.SpeedLoop/BLDC_Speedloop_code/STM32G4_FOC_template`。
不要把旧 PID/NNSMC 接入构建器用于这个模糊 PI 模型；两份 `DW` 的字段不同。

## 构建

`scripts/build_speedloop_diagnostic.py` 使用 GNU Arm 工具链，校验完整私有源树 SHA256，
从 `.uvprojx` 取 42 个原始编译单元，添加 5 个本仓库单元。它不连接板子、不烧录、不运行电机。
未知版本直接拒绝，需要重新审查源文件后更新受审计指纹。

```text
python -B scripts/build_speedloop_diagnostic.py --source PRIVATE_SPEEDLOOP_ROOT --arm-bin GNU_ARM_BIN --output E:/simulink/_codex_tmp/TASK/build
```

GNU 启动代码从受审计的 Keil 向量表提取中断顺序，初始化 `.data/.bss`、C 运行时，保留 4KB 栈与 512B 堆。
构建清单包含编译器版本、输入/输出哈希、初始 SP、复位向量及本镜像符号地址。
回读必须使用该清单，不能沿用旧 Keil map 或上一个 GNU 镜像的 RAM 地址。
临时私有副本、地图、镜像和编译日志全部留在任务临时目录，不能上传公开仓库。

## 与原控制例程的差异

- 原工程和生成的模型源码不改写；诊断构建不执行 `FOC_Model_step()` 或模糊参数更新。
- TIM1 不启动，CH4 也不启动；MOE、三相 CCER、CEN 保持关闭。
- ADC 通道、OPAMP 和原电压/电流标称比例保留。注入改为软件触发，完整序列轮询，约 100Hz，两个 ADC 顺序启动。
- 前 10 个有效注入序列自动校零。计数只在电流与母线转换都完成后递增；失败把观测置 NaN、锁存故障，不刷新采样时间。
- 不声称此采样与 PWM 同步，不能用于电流环或 TD3 的电机运行经验。
- USER3 只停机，USER1/2 不改变给定；启动、增益下发均被锁定端点拒绝。
- SysTick 每 1ms 禁能并检查 Break，前台 5ms 超时锁存；这是软件检查，不等于独立硬件看门狗验收。
- 温度保持 NaN；SpeedLoop 没有对应的历史误差状态，不能借用 NNSMC 字段或把 `Integrator_PREV_U` 冒充原始误差。

## CAN 和身份

500kbit/s 经典 CAN，标准请求 `0x620`、协议响应 `0x621`；原始诊断为 `0x622..0x625`。
固件/配置身份均为 `g431-speedloop-diag-v1`。能力位恒为 0；实机训练器应拒绝它。
完整握手仍需要调试器在断电、暂停状态设置本次唯一的 `motor_td3_g431_debugger_boot_token`，消费后清零。
这不是生产 boot 身份，也不允许从主机自动解锁运动。
具体分帧与诊断布局见 [锁定适配层说明](g431-locked-integration.md)。

## 验证顺序

1. 软件检查：`test_g431_integration.py --speedloop` 与 `test_speedloop_sample.py`，输出指定任务临时目录。
2. 用户确认 24V 物理断开；检查镜像身份、向量和内存范围后才可下载。下载后完整比对 Flash。
3. 保持断电，限时运行读取采样计数、错误计数、偏置、原始码和 PWM 寄存器，再暂停。
4. 有界 CAN 外部诊断需板端收发器 5V 供电和本次功率状态确认。软件 ADC 静态诊断通过不会自动授权功率或运动。
5. 结束清除 MOE/相位 CCER、停止 TIM1、保持暂停，并记录最终状态。

下载前先执行 **reset halt** 并确认 SysTick CTRL=0、TIM1 输出关闭，再加载 Flash 算法；
仅连接到已经暂停的应用仍可能保留启用的 SysTick/NVIC，不能作为下载前复位的替代。
算法异常时保持功率断开，记录 CFSR/HFSR、复位暂停后重试；完整 Flash 比较通过后才运行。

## 有界主机采集

`scripts/speedloop_can_capture.py` 只发送一次 HELLO（15 个标准 `0x620` 分片），
验证响应身份、nonce、准备好的 boot 身份及空能力位，再读取原始 `0x622..0x625`。
它不发送 BEGIN/GAINS/STOP，不复位、不恢复核心、不写内存。
打开适配器后，发送前以不暂停核心的调试连接核对完整 Flash SHA256、
endpoint 就绪、boot token 已消费、无故障及 MOE/CCER/CEN 关闭。
当前入口绑定本次受审计二进制；重新构建的不同镜像必须先审计，不能只改清单冒充。
已修复的握手顺序版本为 32832B，二进制 SHA256：
`90195b9a9e1d06400592e8aac5f31b167eab0fad095ad54ddb361d0f849022a6`。
适配层在同一临界区取握手发送结果和诊断权限快照，防止 SysTick 在两者之间接受 HELLO、
导致首个原始诊断先于身份回复。采集器继续拒绝这种顺序，不忽略未验证数据。

```text
python -B scripts/speedloop_can_capture.py --manifest PRIVATE_BUILD_MANIFEST --pyocd PYOCD_EXECUTABLE --uid PROBE_UID --boot PREPARED_BOOT_HEX --duration 3 --output E:/simulink/_codex_tmp/TASK/capture --allow-live --board-power-confirmed
```

执行前必须根据本次用户确认准备供电；两个命令行标志不能替代确认。
先在 24V 物理断开时初始化、暂停、写唯一 token，短暂运行消费 token，再暂停；
确认板端收发器供电后只恢复该禁止运动程序。此入口不替用户完成这些操作。
PCAN 用正常模式提供 ACK，独占 500kbit/s 通道；不是静默监听。
采集 1～5 秒，拒绝身份/分片/顺序错误、非有限值、ADC 年龄超过 30ms、
输出使能、IRQ 故障及超过 500ms 的诊断中断，不重试或自动重新启动。

结束或采集异常时，针对已完整核验的禁止运动镜像，**先暂停核心并回读禁能状态，再释放 PCAN**。
它在诊断期间从未启动 TIM1，所以暂停可停止其前台 CAN 发送；这不能推广为运行电机的停机操作。
先释放 PCAN 会让仍在发送的板端失去 ACK，产生通信故障。
目标清理不通过时仍释放适配器并报告失败，不自动清故障。
该入口不写外设寄存器；如需单独禁能检查，应使用经过核验的 32 位 TIM1 寄存器访问，
不能假设调试器的半字写入保留其他位。

输出为私有原始帧、调试回读及诊断摘要，不能送入训练器构造状态/动作/奖励。
四个诊断帧来自不同快照，没有设备应用时间/动作序号，不承诺原子一致。
Kp/Ki 是存储值，当前没有运行 PI/FOC；电压、电流采用原标称比例。
软件检查：`python -B scripts/test_speedloop_can_capture.py`，不连接硬件。

此版本用于把真实板端诊断接到 Codex 日志分析，未部署 TD3 Actor，未验收功率输出的过流关断延迟。

已另增 `--watchdog` 禁止运动版本：三种断电故障和真实 CAN 停止心跳复位通过，见 [speedloop-watchdog.md](speedloop-watchdog.md)。原 HELLO-only 镜像入口仍绑定旧诊断版；新版本使用专用看门狗验证入口。
