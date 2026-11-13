# 实验协议与执行记录

## 四组实验条件

| 条件 | Agent 框架 | 基础模型 |
|---|---|---|
| E1 | Pi coding-agent（单轮基线） | GPT-6.1 Sol (`gpt-6.1-sol`) |
| E2 | Pi coding-agent（单轮基线） | DeepSeek V4.1 Flash (`deepseek-v4.1-flash-1017`) |
| E3 | 自研 PLC Agent harness | GPT-6.1 Sol (`gpt-6.1-sol`) |
| E4 | 自研 PLC Agent harness | DeepSeek V4.1 Flash (`deepseek-v4.1-flash-1017`) |

每个条件覆盖相同的 30 道题，温度配置、任务文本、接口、假设和 LTL 对齐；每条件每题一个矩阵单元，共 120 格。Pi 基线使用单轮文本生成并关闭工具；自研 harness 接收编译器反馈，最多执行两轮修复。该资源差异单独报告，并区分首次编译与修复后的最终编译。两种策略的工具权限、反馈和修复预算不同，结果无法隔离框架本身的效果。复测使用原生成源码，未使用 v1.1 规约重新生成。实验顺序使用固定种子打乱。生成输出上限为 768 token。

## 指标口径

- 首次编译结果记录为 `first_compile`，包含 PASS、FAIL 和 TIMEOUT；编译器确实被调用的样本都计入分母。
- 最终编译结果记录为 `final_compile`。独立离线重试更新最终状态，但保留原始首次 TIMEOUT，并在 `experiments/codesys_validation/deepseek_timeout_retries/` 保存单独证据。
- 完整矩阵按 120 个计划单元计算端到端成功率；空输出、失败和未结清超时均不计通过。本次所有 120 格都取得非空 ST，最终无超时。
- 统计报告分子、分母与 Wilson 95% 区间；功能测试和形式验证的 NOT_RUN 不当作通过。
- 成本、token 和请求状态以 usage JSONL 为准；行级 CSV 费用可能缺失或与同模型请求相邻，不能用于单题成本对比。

## DeepSeek 空输出诊断与修复

最初的 DeepSeek 60 格均未提取到 ST。原调用为 HTTP 200，completion token 数均达到 768 上限。受控参数对照发现关闭 thinking mode 后，API 返回可提取的 `content`，且不再把 completion 用在 reasoning-only 输出上。完整恢复矩阵取得 60/60 非空 ST。`config.example.json` 为 DeepSeek 指定禁用 thinking；模型适配器记录 finish reason 与 reasoning 长度等安全元数据，但不保存 prompt、响应正文或密钥。DeepSeek 官方文档说明 thinking mode 默认开启，且 thinking 输出与 `content` 分字段返回；因此本次诊断支持“推理消耗输出预算，未留下可提取正文”的解释，但无法逐条重放最初响应正文。

恢复使用原有 120 格 run ID。DeepSeek 60 个恢复单元的 API usage 实扣 ¥0.476336；诊断与受控 smoke 请求另有日志，不混入矩阵费用口径。

## 原始项目构建记录

本节数值仅供追溯。旧适配器允许未挂接的 POU 取得构建成功记录。当前离线判定见 [120 格统一复测](linked_compile_review/summary.json)。

| 条件 | 单元数 | 首次编译 PASS / FAIL / TIMEOUT | 最终 CODESYS 编译 PASS / FAIL |
|---|---:|---:|---:|
| Pi + GPT-6.1 Sol | 30 | 14 / 16 / 0 | 14 / 16 |
| Pi + DeepSeek V4.1 Flash | 30 | 26 / 2 / 2 | 28 / 2 |
| 自研 harness + GPT-6.1 Sol | 30 | 11 / 19 / 0 | 20 / 10 |
| 自研 harness + DeepSeek V4.1 Flash | 30 | 26 / 2 / 2 | 28 / 2 |
| 合计 | 120 | 77 / 39 / 4 | 90 / 30 |

四个首次编译超时均在模型请求结束后重跑：Pi P15、P11 两份和自研 harness P15 均通过；自研 harness P11 重试后报告 `R_TRIG` 未声明及 ST 结构不完整等编译错误。逐次诊断在 `experiments/codesys_validation/deepseek_timeout_retries/`。因此最终矩阵为 90 PASS、30 FAIL、0 TIMEOUT。CODESYS Control Win x64 Windows 服务在实验时停止，以上是离线项目构建结果，不是 PLC 下载或扫描仿真。

## 自动化测试与有界形式验证加分项

在 P02 的四种输出（Pi/self × GPT/DeepSeek）上使用 STruC++ 0.7.0 运行相同的五项扫描周期测试：数据集的三个 P02 场景，以及 32 位全位上升、全位下降边界。四份输出共 20/20 通过。DeepSeek Pi 输出有一处 STruC++ 不接受的嵌套位移/掩码写法，测试 runner 对执行副本作等价表达式归一化；原 ST 保持不变，转换记录和两个源码哈希均保存在 JSON 结果中。

随后使用 CBMC 5.95.1 对四份 P02 的 STruC++ C++ 翻译代码检查两个任意连续 32 位输入变化和状态更新性质，并执行循环展开、边界、指针、溢出及未定义移位检查。共验证 918 项性质，0 项失败。仅验证 P02 的翻译结果，不代表 CODESYS runtime 等价，也未覆盖其余 29 题或全部 LTL。

在正式矩阵结束后，另行对自研 Agent 的 GPT/DeepSeek 输出运行 Control Win 场景套件，结果单独归档于 `experiments/codesys_validation/self_agent_runtime_20261110.md`。该批次计划 224 个模型-场景组合，实际运行 88 个（82 PASS、6 FAIL），覆盖 56/112 个不同场景 ID；136 个组合因正式离线编译失败或集成测试工程编译失败而未进入 runtime。它不修改正式 120 格结果，也不代表 Pi 基线的 runtime 覆盖。PLCVerif 未安装，PLCVerif/LTL 实际验证数仍为 0。

测试脚本、模板、运行结果和复现说明位于 `tools/run_st_tests.py`、`tools/run_p02_cbmc.py`、`tests/structured_text/`、`experiments/functional_tests/` 和 `experiments/formal_verification/`。

## 成本与记录

- 用户授权累计上限：¥18。
- 正式矩阵 usage：¥5.880938。
- 项目累计 usage（含 pilot、诊断和恢复请求）：¥6.099742，低于上限 ¥11.900258。
- 项目全部 usage 共 234 条记录：233 次 HTTP 200、1 次预算拦截；输入 token 435,406，输出 token 171,446。
- 项目模型费用：GPT-6.1 Sol ¥5.258528；DeepSeek V4.1 Flash ¥0.841214。
- Usage 记录包含模型、token、供应商费用、耗时、HTTP 状态和时间，不包含 API key、prompt 或响应正文。

## 复现配置

矩阵配置见 `config.example.json`。新运行的 CSV、usage 日志和 ST/编译文件默认写入 `experiments/local_runs/`，不会覆盖本次正式矩阵与归档源码。复现时将 API key 放在当前进程的 `DMXAPI_API_KEY` 环境变量中，不要写入配置或提交文件；运行前设置并检查预算上限。CODESYS 编译器版本为 3.5.22.40 / SP22 Patch 4，目标设备为 Control Win V3 x64（`0000 0004`）。P02 STruC++ 和 CBMC 的复现步骤见 `../tests/structured_text/README.md`，新成员从克隆开始的完整命令见 `../docs/REPRODUCING.md`。

## 外部工具资料

- DeepSeek Thinking Mode：<https://api-docs.deepseek.com/guides/thinking_mode/>。
- STruC++ 测试指南：<https://github.com/Autonomy-Logic/STruCpp/blob/development/docs/TESTING.md>。
- CBMC：<https://github.com/diffblue/cbmc>。
