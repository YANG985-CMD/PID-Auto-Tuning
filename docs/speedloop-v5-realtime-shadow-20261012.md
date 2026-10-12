# 2026-10-12：真实电机 MATLAB 实时旁路验证

## 目的

验证“STM32G431 遥测 → Codex 管理的旁路桥 → MATLAB TD3 Actor → Codex 校验与记录”的实时链路。Actor 建议只记录，不改变板端控制器；原有基准 PI、失联停机、增益租约和三相输出保护保持不变。

## 实现

- `matlab/SpeedLoopShadowServer.m` 加载固定的 `experimental-candidate-20261012.mat`，先核对 SHA-256、134 条真实经验和训练完成标志。
- MATLAB TCP 服务器只监听 `127.0.0.1`，每次请求要求私有令牌、协议版本、`shadow_only=true` 和 `hardware_writeback=false`。
- `scripts/speedloop_shadow.py` 在独立线程中发送最新遥测；队列满时只替换旧帧，MATLAB 等待不会阻塞板端采样或停机线程。
- 回复必须匹配原始 `boot_id`、`seq`、`t_us`、状态缩放、Actor SHA 和动作映射。超过 45 ms 的建议只记为拒绝，不会进入板端参数命令。
- 由于训练集只探索 Kp，实时旁路把 Ki 固定为已验证基线 `0.00144`；原始双输出仍记录，但不假装已经验证 Ki 调度。

MATLAB 中可用 `startSpeedLoopShadowServer(checkpoint, tokenFile, 59631)` 启动服务；桥接端使用 `scripts/speedloop_motion_gain_trial.py --shadow-port 59631 --shadow-token-file <token>`。这两个入口都只支持旁路预测，不能写回设备。

## 软件验证

19 项 Python 检查通过，覆盖状态串接、动作限幅、MATLAB 卡顿、超时回复、旧帧、跨会话、错误令牌和禁止写回。随后使用正在运行的 MATLAB R2024b 服务器完成 5 项真实协议检查：握手、预测映射、重复帧拒绝、跨会话拒绝和错误令牌拒绝。

## 实机结果

用户授权一次最多 3 秒、空载、24 V 供电的旁路试验。板端实际运行仍为固定 PI，MATLAB 建议没有下发：

| 项目 | 结果 |
|---|---:|
| 固件 | `g431-speedloop-pi-motion-v5`，SHA-256 `45ad8fcd5039822741d888cb54eaea909cfc55d3e13dc8da0cdfcfc98703cce5` |
| 遥测 / MATLAB 返回 | 148 / 148 |
| 45 ms 内接受 | 148 |
| 往返延迟 p50 / p95 / 最大 | 6.17 / 7.83 / 13.68 ms |
| 实际 Kp/Ki 应用 | 54 次基准增益保活；`0.003389 / 0.00144` |
| 名义峰值电流 / 峰值速度 | 1.032715 A / 1782.531 rpm |
| 故障 / 最终 IRQ、TX 故障 | 0 / 0、0 |
| STOP、六路输出、核心 | 已确认、已关闭、已暂停 |

名义电流尚未用受控电流源独立标定，板上没有温度传感器；这次仍是用户明确授权的无温度门短试验，不改变正常训练和部署门槛。

## 结论和限制

实时数据链路和时限验证通过。Actor 尚未写入增益，不能用这次结果声称 TD3 优于固定 PI，也不能称为 Actor 的闭环性能测试。要做固定 Actor A/B，需要新的实机预算、未参与训练的工况和独立回退规则。

之后对 148 条建议执行了离线动作审计：全部与原始板端帧对齐，增益范围和单步范围通过，Ki 掩码保持 `0.00144`。审计明确标记 `counterfactual_performance_evaluated=false`，没有把基准 PI 的响应冒充 Actor 响应。

完整原始文件见 [`examples/speedloop-v5-real-20261012/realtime-shadow-20261012`](../examples/speedloop-v5-real-20261012/realtime-shadow-20261012/)。
