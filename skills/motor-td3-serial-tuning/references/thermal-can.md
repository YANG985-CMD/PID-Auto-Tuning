# 热预算的 CAN 诊断反馈

## 范围与身份

这是 **禁止运动固件的诊断扩展**，用于让 Codex 分析热预算和拒绝原因。它不产生 TD3 经验，不替代 CAN v1 的实测温度，不宣布新的训练能力。`verified_alternative` 仍被运行器拒绝。

- 固件与 profile：`g431-speedloop-heat-can-v1`，HELLO 能力为 0。
- HELLO 请求/响应仍为 `0x620/0x621`；普通原始诊断仍为 `0x622..0x625`。
- 新热诊断仅使用标准经典 CAN 数据帧 **`0x626`**，8 字节，不接受扩展帧/RTR/FD/错误帧。
- `motor_td3_speedloop_thermal_packet` 在单一前台保护任务中一次复制完整状态；不得与热状态更新并发。它只读，不调用 `check/may_start`、禁能或清故障。
- 构建器只修改私有副本的适配层：先发完 HELLO，然后复用原有唯一 `send_frame` 与实际 Tx event 检查。每次仅一帧未确认，整包发送期限 50ms；热包完成后至少间隔 100ms 再取下一份。RX、采样和看门狗继续由各自任务运行。
- 旧下载器和采集器只支持其已核验的固定镜像，拒绝本身份。本轮没有提供新的实机下载/采集入口；不得直接改旧白名单来测试。

## 载荷布局

整数均为小端，float/double 为 IEEE-754 binary32/binary64；不直接复制 C 结构体。固定长度 **144 B**，前 140 B 的 CRC32 使用 IEEE 多项式，与已有协议一致。

| 起始偏移 | 字节 | 字段 | 单位/规则 |
|---|---:|---|---|
| 0 | 4 | magic | ASCII `THT1` |
| 4 | 1 | version | 1 |
| 5 | 1 | reserved | 0 |
| 6 | 2 | length | 144 |
| 8 | 8 | nonce | 必须与已验证 HELLO 相同 |
| 16 | 8 | boot token | 必须与已验证 HELLO 相同；诊断 token 不是生产可信启动身份 |
| 24 | 4 | snapshot sequence | 非零，单次启动递增，溢出即拒绝；离线审计检查连续性 |
| 28 | 4 | flags | 下表；未知位拒绝 |
| 32 | 2 | feed fault | 采样接入的首个故障 |
| 34 | 2 | thermal fault | 热 guard 的首个故障 |
| 36 | 8 | capture time | MCU 微秒时钟，整包取样时刻 |
| 44 | 8 | accepted sample sequence | 已接受样本数，未收到为 0 |
| 52 | 8 | last sample time | 微秒，未收到用 UINT64_MAX |
| 60 | 8 | completed window sequence | 完整窗口数，未收到为 0 |
| 68 | 8 | last window end | 微秒，未收到用 UINT64_MAX |
| 76 | 24 | used[3] | 三相 double，A²·s；未知为 NaN |
| 100 | 12 | budget[3] | 三相 float，A²·s；限值未验证为 NaN |
| 112 | 8 | energized time | 累计实际输出活动时间，微秒；未知用 UINT64_MAX |
| 120 | 8 | stalled time | 累计堵转时间，微秒；未知用 UINT64_MAX |
| 128 | 4 | sample period | 微秒；无已验证限值为 0 |
| 132 | 4 | max observation age | 微秒；无已验证限值为 0 |
| 136 | 4 | window duration | 微秒；无已验证限值为 0 |
| 140 | 4 | CRC32 | 覆盖 0..139 |

| 位值 | 含义 |
|---:|---|
| 1 | 电流校准记录已经通过接入层的数值/范围检查 |
| 2 | 热限值通过 guard 配置检查 |
| 4 | 初始热 seed 完整且已知，包括启动时已超限的 seed |
| 8 | 已接受完整三相校准样本 |
| 16 | 已接受完整热窗口 |
| 32 | 累计预算/持续时间可解释，必须等价于限值与 seed 均已知 |
| 64 | 样本在取包时刻未超过 `period + max_age` |
| 128 | 窗口在取包时刻未超过 `window_duration + max_age` |
| 256 | 这是禁止运动诊断架构；**不等于物理 PWM 回读或启动许可** |

这些位表示代码读取到的记录状态，不能代替记录背后的真实工程验证。`seed_known` 只有在三相预算及持续时间一致性检查完成后置位；坏 seed 即使部分字段已复制，仍全按未知输出。启动时已超限的有效 seed 保留数值并报告故障。

feed fault：0 无，1 初始化，2 校准，3 热 guard，4 ADC，5 序号，6 时间，7 过期，8 采样峰值。thermal fault：0 无，1 配置，2 未知启动热状态，3 传感器，4 序号，5 时间，6 过期，7 电流，8 预算，9 堵转，10 累计通电时限。首故障不清除，STOP 不重置预算。

分帧沿用 `D1 | transfer_u8 | index_u8 | length_u8 | payload[4]`，144 B 共 36 帧。tag/序号/长度必须一致，严格顺序，50ms 内完整到达；CRC 防止同 tag 混入另一快照。完成后还须核对 nonce、boot、snapshot sequence 与字段有效性。CRC 不提供来源认证。

## 离线读取

```text
python -B skills/motor-td3-serial-tuning/scripts/test_thermal_can.py --output TASK_TEMP_TEST --compiler GCC
python -B skills/motor-td3-serial-tuning/scripts/thermal_can.py --log RAW_JSONL --output TASK_TEMP_AUDIT
```

Windows 输出须在用户指定的 `E:\simulink\_codex_tmp\` 独立空目录。输入格式与仓库静默监听器 `scripts/can_monitor.py` 的原始 JSONL 相同；本解析入口不打开硬件。输出 `summary.json` 与 `snapshots.jsonl`，未知值转成 JSON `null`，提供三相预算占比、累计时间、故障和中文拒绝原因。

解析器要求准确的零能力 HELLO；身份、会话、CRC、丢帧/重排/混包、重放、时钟倒退、非法数值、虚假的 fresh 位、热预算下降、首故障清除或启动内配置变化都会使审计失败。报告 `passed` 仅表示日志结构一致；快照中可以有真实故障。`motion_approved`、`thermal_protection_verified`、`live_freshness_verified` 始终为 false。

`fresh_at_capture` 只描述 MCU 取包时刻，日志和链路延迟不会变成实时保护证据；离线记录也不能证明结束后电机或温度现状。采样的 100Hz 顺序转换与 1ms 时钟仍只是禁止运动接线诊断。

## 实机仍缺少的证据

实际三相电流校准、连续相 RMS/过载曲线、功率板热边界、热状态恢复、实际 PWM 采样覆盖、保护执行时间、运动停机、急停和可信启动身份均须完成。当前 SpeedLoop 的校准/限值/seed 为缺失记录，预期仍锁存 `TD3_FEED_CALIBRATION`。任何软件样例里的校准和热参数都不得移入该板的只读配置。
