# 固定热诊断镜像的板上验证

`scripts/thermal_diagnostic.py` 专用于 `g431-speedloop-heat-can-v1`。它验证缺失校准时的拒绝状态，保持零能力，没有电机启动、增益写入或 TD3 训练入口。真实热保护仍需电流、限值、热状态和功率板依据。

## 镜像与目标检查

- STM32G431/G441 调试身份 `0x468`、128KB Flash；本次实际目标为 STM32G431。
- 固定镜像 43580 B，SP=`0x20008000`、入口=`0x080001D9`。
- BIN SHA256：`69909f289ae5f5bd0f1d4b7fbe888f08f6d2cd3ddc389b363fa99374ca8f9856`。
- HEX SHA256：`1cc3cdd3cb47f9432643bdd1de0c0bdb1fd6874701ec5f78bc9d64dd6f342766`。
- 下载前同时验证来源工程、模型、接入源码、禁止运动合同、符号位置及 Arm ABI 布局。布局来自 Arm 编译器的 `sizeof/offsetof`，未把布局审计对象链接进固件。
- 使用独立入口；旧固定镜像下载器继续拒绝新身份。不靠改旧白名单跨版本运行。
- 每次 CAN 会话前读取两份完整镜像并检查核心暂停及 TIM1 的 `CEN=0、CCER=0、MOE=0`。诊断报文中的 LOCKED 位不能代替寄存器检查。

## 顺序与供电确认

必须依据现场最新供电状态执行，命令行开关不能代替用户确认。所有私有构建、日志和一次性会话须在 `E:\simulink\_codex_tmp\` 的独立任务目录；每个输出子目录必须不存在。

先在实际运行的 Python 环境配置 `scripts/requirements-can.txt` 和 PCANBasic 驱动；使用独立依赖目录时，必须在每次调用中设置该环境的 `PYTHONPATH`。下面的 `dependencies` 只加载库，不初始化 CAN 通道、不访问 STLink。`prepare` 与 `run` 也会先检查依赖，缺失时不复位板子、不消耗会话；通过库加载检查后，通道占用或驱动故障仍可能使真实初始化失败。

```text
python -B skills/motor-td3-serial-tuning/scripts/thermal_diagnostic.py validate --build TASK_TEMP_BUILD
python -B skills/motor-td3-serial-tuning/scripts/thermal_diagnostic.py dependencies
python -B skills/motor-td3-serial-tuning/scripts/test_thermal_diagnostic.py --output TASK_TEMP_TEST
```

1. **24V 物理断开、USB/STLink 保持供电**后 `flash`。先核对芯片与选项字节，再 reset halt、检查 SysTick/PWM 已复位，备份完整 128KB Flash，下载经过核验的 HEX。全量回读后运行 600ms；运行期间 IWDG 不受调试冻结。暂停后才冻结以读取状态，最后 reset halt、恢复原冻结设置并核对镜像/选项。失败也尝试收尾，不自动恢复或启动电机应用。

```text
python -B skills/motor-td3-serial-tuning/scripts/thermal_diagnostic.py flash --build TASK_TEMP_BUILD --output TASK_TEMP_FLASH --pyocd PYOCD --uid LOCAL_PROBE_UID --pack LOCAL_DEVICE_PACK --power-stage-disconnected --reset-and-halt-ack
```

2. **保持 24V 物理断开**后 `prepare`。核对实际完整镜像，运行约 300ms，确认采样/前台健康与准确的缺失校准状态，再暂停、冻结 IWDG，写入并回读一次性 RAM token。它不是生产可信启动身份。准备失败则断电复位收尾。

```text
python -B skills/motor-td3-serial-tuning/scripts/thermal_diagnostic.py prepare --build TASK_TEMP_BUILD --output TASK_TEMP_PREPARE --pyocd PYOCD --uid LOCAL_PROBE_UID --power-stage-disconnected
```

3. **用户确认 24V/3A 已接通，不按 USER3/RESET**后 `run`。会话有效期 20 分钟，先独占登记一次性使用，失败也不能重试该会话。再次核对镜像、token、冻结及状态。先初始化 PCAN 提供 ACK，再恢复已核验的禁止运动核心；唯一 CAN 线程只发送 HELLO 和 STOP 心跳。

```text
python -B skills/motor-td3-serial-tuning/scripts/thermal_diagnostic.py run --session TASK_TEMP_PREPARE/session-private.json --output TASK_TEMP_CAPTURE --channel PCAN_USBBUS1 --allow-live --board-power-confirmed
```

采集到约 3 秒后的完整热快照结束主日志；50ms 分帧、350ms 新鲜度、8 秒线程总时限仅为诊断合同，不能当作运动保护阈值。握手、CRC、会话、序号、故障/输出或新鲜度不一致时停止采集，不自动重握手。收尾期间继续 STOP/ACK，**先暂停并检查核心/PWM，再停线程和释放 CAN**；带电时不复位。收尾尾帧另存，不能把未完成热包当作完整审计证据。

4. 核心暂停、CAN 释放后请求用户 **物理断开 24V**，再 `finish`。核对完整镜像，reset halt 清理会话，恢复调试冻结，核对选项字节；最终保持核心暂停/PWM 禁能。

```text
python -B skills/motor-td3-serial-tuning/scripts/thermal_diagnostic.py finish --session TASK_TEMP_PREPARE/session-private.json --output TASK_TEMP_FINISH --power-stage-disconnected
```

## 预期状态与结论

本镜像的电流校准、热限值和初始 seed 均缺失，正确结果为 `feed_fault=calibration、thermal_fault=config`，三相预算/累计时间未知、已接受样本和窗口均为零。热保护拒绝状态与正常原始 ADC 采样计数可以同时存在：没有校准的 ADC 原始码不会被当成安培写入预算。

离线解析沿用 [thermal-can.md](thermal-can.md)。Codex 能根据拒绝原因和板端状态分析下一步缺口，管理构建、烧录、数据审计与收尾。诊断通过不批准电机转动，不证明实际过流安培门槛/热阈值，也不形成 TD3 经验。

完整固件、恢复备份、芯片序列号、nonce/token 与原始实测日志保持本地；公开仓库只交付脱敏摘要和来源指纹。
