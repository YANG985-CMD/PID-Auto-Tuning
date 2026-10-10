# STM32 固件接入与验证

## 现成文件

- `firmware/motor_td3_protocol.c/.h`：固定内存 JSON 命令解析、CRC32、hello 和遥测编码。
- `firmware/motor_td3_guard.c/.h`：增益边界/步长、命令序号、租约、失联、试验时限、传感器/电流/转速/电压/温度、故障锁存。
- 导出的 `motor_actor.c/.h`：仅本机推理，不含训练、Critic 和回放池。
- `stm32_actor_pil.c/.S` 与 `scripts/stm32_actor_pil.py`：G431/G441 128KB 目标的计算专用 RAM PIL，比较 MATLAB 输出并读取 MCU 周期计数；不含电机控制接入。

这些模块是可编译的 C99 参考实现。板级 UART、计时、PWM 禁能、传感器、无扰 PI 更新与工程构建接入点仍取决于目标工程，不能只复制文件就宣称独立保护生效。

## 板上任务划分

1. UART 接收任务只收完整帧，验证 CRC 并解析为 `motor_td3_command`。放进单槽最新命令队列；禁止积压动作。超过 1,024 字节、错误 CRC、无效字段、队列溢出等立即请求经验证的故障停机，丢弃至 LF，禁止把尾部片段当作新命令。
2. 控制周期边界取命令，完成身份和模式检查，然后调用 guard。`hello`/`begin` 的 `profile_id` 必须匹配固件内固定配置；`begin.speed_ref` 必须匹配本次已验证给定计划。使用 `lease_ms * 1000` 前检查不超固件上限。
3. 高优先级控制任务每周期调用 `motor_td3_tick`，随后**实际调用 PWM/驱动禁能**处理 `!guard.enabled`。guard 里的布尔值自身不会关闭 MOSFET；硬件过流、急停与门极驱动保护仍独立存在。
4. `gains` 仅在 `motor_td3_apply` 成功后原子更新速度 PI。连续 Ki 在积分器使用 `Ki × Ts × error`；已有积分器若采用离散 Ki，配置要标明并使用相同定义。不得再次乘/遗漏 Ts。
5. 回报的是控制器真正采用的 Kp、Ki、序号及设备 `t_apply_us`，不能仅回显接收缓冲区。反馈序号在同一次 boot 内单调递增；bridge 从当前 `applied_seq` 接续命令，普通停止不会清零序号。
6. 网络运行、主机调参、模糊 PI 和手动调参只能有一个写入者。进入 AI 模式时明确禁止其他路径覆写增益；退出按已验证规则回到原控制模式。拒绝后先停机，不自动转动电机尝试恢复。

## JSON CRC 协议

完整帧为 `ASCII_JSON*CRC32_HEX8\n`。CRC 使用标准 IEEE CRC32，覆盖 `*` 前的原始 JSON 字节；空格也参与校验。
命令 parser 仅支持本工作流的固定字段，不支持嵌套 JSON 或字符串转义；身份字符串只允许字母、数字、`-_.`。不要换成旧的 `P3...!`/`P4...!` 单参数写法。

| 命令 | 必须且仅能包含这些字段 |
|---|---|
| `hello` | `type, profile_id` |
| `begin` | `type, profile_id, speed_ref, lease_ms` |
| `gains` | `type, command_seq, kp, ki, lease_ms` |
| `stop` | `type` |

`hello` 回复：

```json
{"type":"hello","protocol_id":"motor-td3-json-crc-v1","firmware_id":"BOARD_FIRMWARE_VERSION","profile_id":"VERIFIED_PROFILE_ID","boot_id":"UNIQUE_BOOT_ID","capabilities":["atomic_gains","applied_feedback","lease","link_watchdog","fault_latch","single_owner"]}
```

仅在这些功能已实际接入并验证后声明 capabilities。`boot_id` 每次重启改变，例如持久化启动计数和硬件标识组合，不用恒定字符串。运行中再次 hello、时间倒退、序号丢失或 boot 身份变化都会使本次桥接器停止。

每个遥测帧应来自一致的控制状态快照。调用 `motor_td3_encode_telemetry` 生成帧，包含：`type,boot_id,seq,t_us,t_apply_us,applied_seq,fault,enabled,speed_ref,speed,error_history,integral_output,current,vbus,temperature_c,kp,ki,elapsed_ms`。发送频率、波特率和窗口须根据实际帧长测算，避免环形缓存溢出。状态 float32 至少用 9 位有效数字以保留应用值回读；示例编码已这样处理。

`t_us`、`t_apply_us` 使用不倒退的 64 位微秒时间。32 位微秒定时器约 71 分钟回绕，必须在固件正确扩展，不能直接冒充 64 位。`seq` 和 `command_seq` 为 uint32；会话应在溢出前停止并重新建立。

租约/失联计时由 MCU 控制任务运行。有效 gains 才更新 `last_rx_us` 与动作租约；普通 hello/心跳不续动作。`stop` 为正常禁能；过流、非法动作、失联等 fault 锁存，guard 没有远程清故障接口。

## Actor 上板方式

串口训练阶段 Actor 在 MATLAB；板上保留速度 PI。部署阶段只把 Actor 作为增益调度器迁移到 MCU，输入数据、尺度、field 顺序、动作映射和执行周期必须与训练相同。不得把部署后动作周期改成电流环周期而沿用原策略。

板级决策任务的一次动作示意：

```c
/* raw_state[10] must be a coherent measured snapshot in the documented units. */
float action[2], gains[2];
if (!motor_actor_predict(raw_state, action, gains)) {
    board_latched_safe_stop();
} else if (!motor_td3_apply(&guard, board_time_us(), next_command_seq,
                           gains[0], gains[1], verified_lease_us)) {
    board_latched_safe_stop();
} else {
    board_set_speed_pi_bumpless(guard.kp, guard.ki);
}
/* These board functions are explicit integration hooks, not supplied HAL APIs. */
```

嵌入式模式继续使用本地租约与试验预算；如果不再依赖主机通信，应将“本地决策进展”和“串口主机失联”的保护模式按验证结果分开，不得为了让它运行直接关闭所有看门狗。

## 部署验证顺序

先用 `actor_codegen.py` 进行主机 C 对齐；再纳入目标编译器，检查 stack/Flash/RAM 报告；随后 SIL/PIL 和板上执行周期测试；最后在已授权的受限电机试验中和已验证基准比较。MCU 是 Cortex-M4F 时使用单精度，确认 `tanhf` 链接和最坏执行时间，不在 FOC 中断里运行主机导出的训练代码。

本仓库没有某块开发板的自动烧录配置。Codex 接入实际工程时须查明构建产物、下载器和板卡身份，再按用户已经授权的会话构建/烧录；无法获得板卡和保护验证信息时仍可完成导出、主机编译与接入补丁，但应报告尚未做过上板验证。

本仓库提供的 [RAM PIL](stm32-ram-pil.md) 已在实际 STM32G431 上执行。它把 Actor 计算部署到 SRAM，在断开功率电源的条件下验证数值；原 Flash 保持不变，结束让核心暂停。永久部署仍须在目标工程中接入真实输入、保护与唯一增益写入者，完成实际周期测量及受限闭环验收。
