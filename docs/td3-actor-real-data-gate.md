# TD3 Actor 的真实电机数据门槛

仓库中的 `examples/mock-validation/actor.json` 只用于 MATLAB 与 C 的数值对齐、MCU RAM PIL 和故障输入测试。它没有使用这块 STM32G4 电机的运行数据，不能接管 `17.SpeedLoop`。

真实 Actor 必须来自一条可追溯的经验链：

1. 使用已验证的基线控制器采集电机状态、实际生效的 `Kp/Ki`、设备时间、响应窗口、奖励和故障记录。
2. 只把应用确认、时序连续、没有安全干预的记录送入 TD3 回放池。基线试转的重复数据可以作为状态参考，但不能伪装成不同动作的训练经验。
3. 在至少 3 个完整工况、128 条有效转移和 8 个以上局部动作点后，冻结归一化和动作映射，再训练 TD3。
4. 用未参与训练的工况评估候选，确认电流、超调、饱和、故障和最差误差，再导出 Actor。
5. 导出的 `actor.json` 必须包含 `training_data`，其中记录数据集哈希、固件/协议身份、有效转移数、工况数和动作覆盖数。

导出器可用 `--require-real-motor-data` 强制执行这道检查：

```text
python -B skills/motor-td3-serial-tuning/scripts/actor_codegen.py \
  --model REAL_ACTOR_JSON --output ACTOR_OUTPUT \
  --reference MATLAB_REFERENCE_JSON --compiler gcc \
  --require-real-motor-data --dataset TRANSITIONS_JSONL
```

`--dataset` 会重新计算桥接器保存的 `transitions.jsonl`，必须与 Actor 内的
`training_data.dataset_sha256` 完全一致；缺少数据文件或哈希不一致时，Codex 拒绝导出用于部署的 C 代码。

当前仓库没有满足该门槛的真实 TD3 Actor。此前的 3 秒 `17.SpeedLoop` 试转是基线遥测，未应用 TD3 增益，也没有形成可训练的动作覆盖。因此当前正确状态是“Actor 接口和校验已准备，实际 Actor 等待真实数据采集和训练”，而不是把 `candidate-020` 接到电机上。
