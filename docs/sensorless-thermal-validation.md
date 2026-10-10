# 无温度传感器的 MCU 热预算：软件验证

日期：2026-10-11。范围为离线源码与合成电流测试，没有连接下载器、重新烧录、改变当前固件或启动电机。

本页记录第一阶段的独立热模块验证，摘要中的“未链接”状态保持历史含义。后续已增加原始 ADC 接入层，并在禁止运动 SpeedLoop 副本完成 52 单元完整链接，仍未烧录；见 [热接入离线验证](thermal-feed-integration-validation.md)。

## 做了什么

Codex 核对本地示例和手册电流单位，编写 MCU 独立保护模块，运行故障测试并分析结果。三相热负荷、累计低速堵转时间和累计相桥使能时间由 MCU 判断；TD3 仅调已批准的速度 PI，不能改变这些限值。Codex 可以读取保护记录分析实验，但不参与实时停机判断。

| 检查 | 结果与范围 |
|---|---|
| 三相过载预算 | 17 组 C 主机测试通过，包括三相分别达到热预算、停机后保留预算、堵转/通电累计、未知启动状态和丢失/异常采样；使用合成参数 |
| Cortex-M4 编译 | GNU Arm 14.2 编译对象文件通过；未链接至 SpeedLoop、未测量 MCU 执行时间、未烧录 |
| 桥接保护回归 | 15 项测试通过，增加“替代热配置不能绕过实机 guard”检查 |
| CAN 桥接回归 | 16 项测试通过，原协议/实际应用反馈和模拟会话仍可工作，没有打开硬件 |
| 真实热保护验收 | **尚未完成**：电流增益、电机连续/过载热限值、功率板热保护和冷机/持久状态恢复均缺验证 |

原始公开摘要：[thermal-summary.json](../examples/sensorless-thermal/thermal-summary.json)、[runtime-summary.json](../examples/sensorless-thermal/runtime-summary.json)、[can-runtime-summary.json](../examples/sensorless-thermal/can-runtime-summary.json)。摘要中的 `thermal_protection_verified=false` 和 `linked_into_speedloop=false` 必须保留。

## 保护行为

先对每个采样的相电流平方，再求窗口平均，得到每相均方电流。对超出连续相 RMS 电流平方的正值积分，三相分别维护 A²·s 预算；任一达到上限就调用实际相桥禁能 hook，并锁存故障。第一版不扣除未经验证的冷却量。低电流、停机和新回合不清零；未知启动热状态拒绝运行。

采样无效、窗口时延/采样数错误、序号重放/丢失、时钟倒退与独立采样超时均会禁能。热模块不负责短路尖峰：快速过流仍需经验证的 COMP/TIM1 Break。绕组 I²t 也不能独自覆盖 MOSFET 开关损耗和散热异常。

实现与接入责任详见 [sensorless-thermal.md](../skills/motor-td3-serial-tuning/references/sensorless-thermal.md)。初始化先关闭输出，保护参数来自只读工程配置；无远程清故障 API。持久化预算与冷机流程尚待实现，所以不能把普通 MCU 复位当作热保护复位。

## 资料审计

| 资料 | 能支持的结论 | 尚不能支持的结论 |
|---|---|---|
| V13.1 用户手册 PDF 第 13 页；测试手册第 6 页 | 配套电机 24 V、1300 rpm 等示例信息 | 当前电机连续相 RMS 电流、过载允许时间、热曲线 |
| V13.1 用户手册 PDF 第 24 页截图 | MCSDK 示例设置 `Nominal Current=3.00 Apk` | 不证明这是当前电机连续 RMS 额定值；不能直接填 3 A RMS |
| CAN Hall 示例 `pmsm_motor_parameters.h` | `NOMINAL_CURRENT=2183` 是依赖采样链路的内部 int16 码值 | 不是安培数，也不证明过流阈值已标定 |
| 用户的 24 V/3 A 电源 | 输入电源配置 | 相电流额定值及绕组/MOSFET 热边界 |

没有上传厂家手册页面或工程源文件；这里只保存核对结论。三相零点记录可沿用检查，电流幅值增益仍需独立标定。先取得增益、连续相电流与过载/功率板依据，随后进行禁止运动接入和故障链路验证，再安排受限基准试验。

## 参考原理

[Kollmorgen I²t 保护](https://webhelp.kollmorgen.com/studio/Content/Kollmorgen%20Studio/7%202%20I2T%20Motor%20Overload%20Protection.htm)给出了超额电流平方积分和允许峰值时间的关系；[Synapticon 逐相 I²t 与堵转说明](https://www.synapticon.com/en/motion-control-academy/motorueberlastschutz-i2t-stillstandsschutz)说明了低速时单相热负荷的问题。本版增加了不提供冷却抵扣、累计时间和未知启动状态禁止运行的限制。算法来源不等于本电机参数已经验证。
