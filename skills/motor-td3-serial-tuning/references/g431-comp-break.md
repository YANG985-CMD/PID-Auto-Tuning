# G431 比较器与 Break 的断电诊断

此步骤用于已核对的 STM32G431/H17 电机板：功率电源物理断开后，运行专用 SRAM 程序，通过内部 DAC3 CH1 阈值变化，让静止的 OPAMP3/PB1 电压与阈值交叉，观察真实 COMP1 输出和 TIM1 BIF。不能在其他板卡上仅凭相同芯片 ID 执行。

## 条件和范围

- 先核对板卡、原理图和一个 STLink；芯片检查限定器件 ID 0x468、Cortex-M4、128KB Flash。取得功率电源断开的现场确认，控制部分仍有供电。现有会话确认有效时不重复询问；发现重新上电等状态变化时核实当前供电。
- 会暂停并复位 MCU、覆盖前 20KB SRAM；不写 Flash、不恢复原应用、不访问 CAN/串口。结束比较完整 Flash 并保持核心暂停。
- guest 只开启 OPAMP3、COMP1、DAC3、TIM1 及 GPIO A/B 读取时钟；不写 GPIO 模式或相位输出寄存器的使能值。MOE=0、CCER=0、CEN=0，PA8/9/10 与 PB13/14/15 保持复位模拟模式。外设时钟在结束时关闭。
- 改变的是内部比较门槛，不是电机电流。阈值 0、3000、4095 及二分查找仅用于本诊断；不是实机保护设置或允许电流。
- TIM1 配置与审计工程一致：COMP1 高有效，BKE=1、BKP=1、BKF=2、AOE=0、死区码 120。HSI16 的 SWS 状态编码为 `0x4`，不是 0；guest 同时核对 HSI ready。
- 全程 MOE 为 0，所以**不验证 MOE 从 1 自动清零、功率引脚波形、真实封波延迟或三相正负电流保护覆盖**。

## 构建和执行

路径相对本 skill 根目录，Arm Compiler 6 与 CMSIS 树来自已审计的私有工程；输出是用户指定临时根目录中的独立新目录。

```text
python -B scripts/g431_comp_break.py build --arm-bin ARM_COMPILER_BIN --cmsis-root PRIVATE_FOC_ROOT/Drivers/CMSIS --output NEW_TASK_TEMP_BUILD
python -B scripts/test_g431_comp_break.py --output NEW_TASK_TEMP_CONTRACT_TEST
python -B scripts/test_g431_integration.py --compiler GCC --output NEW_TASK_TEMP_ADAPTER_TEST
python -B scripts/g431_comp_break.py run --build NEW_TASK_TEMP_BUILD --output NEW_TASK_TEMP_RESULT --power-stage-disconnected --reset-and-halt-ack
```

最后两个标志记录已取得的断电确认和 RAM 操作授权，不能替代物理断开。运行器校验固定 SRAM 布局、入口、镜像和当前随包源码指纹；不接受任意用户 C 程序。需要 pyOCD，依赖和会话设置与其他 RAM PIL 相同。

## 结果判定

`result.json` 同时检查以下证据，任一失败不开放运动能力：

1. guest 完成状态正确、8/8 检查通过、17 条诊断寄存器样本均输出隔离。
2. DAC 4095/3000 时 COMP1 为低、BIF 清零；DAC 0 时 COMP1 为高且 BIF 置位。
3. 阈值恢复并清除硬件标志后，诊断程序的软件故障仍锁存。
4. 12 次二分步骤与原始寄存器轨迹相符，得到静止输入的 DAC 交叉区间；它仅表明零电流附近电压的交叉，不是安培校准。
5. 外设关闭、栈底围栏完整、完整 Flash 未变、核心最终暂停。

`mailbox.json` 和 `trace.json` 便于失败诊断。失败/超时也尝试复位暂停和 Flash 比较，不自动运行原程序或放宽保护。第一次若在前置检查退出，应按实际错误定位代码或状态；不能直接去掉检查。

实际锁定适配层另用主机测试核验 BIF/B2IF/SBIF 的 1ms 检测、清标志后仍锁存、STOP/BEGIN 不能解除故障。这些是实际适配层代码在替代 HAL/寄存器上的软件证据，完整 HAL/FOC 的板上行为仍待验证。

## 已完成的一次试验

2026-10-11，断开 24V、USB/STLink 供电：8/8 通过，17 次寄存器采样均隔离；DAC 交叉码为 2033～2034；镜像 4,448 B、观测栈使用 40 B、总流程 371,467 周期（16MHz 下约 23.2ms，**不是封波延迟**）；结束核心暂停、Flash 未变。实际适配层软件检查 24/24，诊断入口/异常收尾检查 14/14。完整 FOC 重建 45 单元通过，未烧录运行；能力仍为 0。

硬件机制依据 ST [RM0440 的 Break 功能说明](https://www.st.com/resource/en/reference_manual/rm0440-stm32g4-series-advanced-armbased-32bit-mcus-stmicroelectronics.pdf)：Break 状态置位 BIF；BIE 控制中断请求，不能将二者混为一谈。AOE=0 也不能替代应用对故障及启动入口的锁存。
