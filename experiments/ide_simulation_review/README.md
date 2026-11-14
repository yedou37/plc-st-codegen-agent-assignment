# CODESYS IDE 模拟功能复测

在 CODESYS V3.5 SP22 Patch 4 的 IDE 模拟器中，用 50 ms 周期任务执行原始归档 ST。52 份源码已通过离线挂接编译，其中 51 份通过题目接口检查并全部进入模拟执行。P18 的一份 Pi + GPT 输出用 DINT 和开放数组替换了题目声明的 VARIANT。

| 策略和模型 | 全套场景通过的输出 / 题目 | 场景通过 / 已执行 / 计划 |
|---|---:|---:|
| Pi + GPT | 16/30 | 63/64/112 |
| Pi + DeepSeek | 8/30 | 34/35/112 |
| 自研 + GPT | 15/30 | 61/63/112 |
| 自研 + DeepSeek | 9/30 | 37/37/112 |
| 合计 | 48/120 | 195/199/448 |

199 个实测场景中有 4 个断言失败，覆盖 19/30 道题和 72/112 个不同场景 ID。其余 249 个场景组合对应未取得合格离线源码或接口不符的实验格。

- [interfaces.json](interfaces.json) 记录 52 份候选的接口匹配情况及源码 SHA-256。
- [results.jsonl](results.jsonl) 包含最新向量下每份原始源码的实测结果、SHA-256 和期望值。[prior_vector_results.jsonl](prior_vector_results.jsonl) 保留了修正 S08 状态预置、S02 输入序列、P05 和 P13 计时方案之前的 10 份结果。
- [targeted_repairs.jsonl](targeted_repairs.jsonl) 记录三份人工修订的实测证据。P05 修订了上电定时器完成状态的锁存，P14 两份源码修订了字符串字节索引。[修订源码](targeted_repairs/) 通过 9/9 个场景。
- [summary.json](summary.json) 给出四个条件的完整运行分母和覆盖情况。本轮模型调用 0 次。

历史 Control Win 服务测试和 IDE 模拟器的结果分别来自不同运行目标、候选筛选和向量版本。复现命令见 [运行说明](../../docs/REPRODUCING.md)。
