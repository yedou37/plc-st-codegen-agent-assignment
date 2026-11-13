# PLC 结构化文本代码生成大作业：提交说明

本文件供助教快速定位交付内容。详细复现步骤见 [`docs/REPRODUCING.md`](docs/REPRODUCING.md)，验收对照见 [`验收对照表.md`](验收对照表.md)。

## 提交目录

- `dataset/tasks.json`：30 题的统一数据集；包含接口、显式假设、LTL 和测试场景。
- `dataset/synthetic_tasks.json`、`docs/DATASET_SPEC.md`、`dataset/build_dataset.py`：10 道原创题的来源、设计审查及数据集重建依据。
- `src/`：自研 Agent、DMXAPI 模型适配器、ST 输出抽取和静态预检查。
- `experiments/run_matrix.py`、`tools/`：实验运行、计量预算、CODESYS 编译、复测、补充测试和打包脚本。
- `st/runs/`：正式实验生成的 Structured Text 源码和相应编译日志；`attemptN` 文件保留自研 Agent 的修复尝试。
- `experiments/results.csv`、`experiments/results_summary.json`：正式 120 格矩阵及统计汇总。
- `experiments/codesys_validation/`、`experiments/posthoc_repair/`：四个矩阵超时重试和修正适配器复测证据；原始逐格编译日志与 ST 在 `st/runs/`。
- `experiments/codesys_validation/self_agent_runtime_20261110.md`：自研 Agent 两模型在 Control Win 上的 runtime 场景结果；机器可读断言汇总与运行脚本一并提交。
- `tests/structured_text/`、`experiments/functional_tests/`：P02 STruC++ 测试模板与四份结果。
- `experiments/formal_verification/`：四份 P02 翻译输入、CBMC harness、日志和结果。
- `experiments/diagnostics/deepseek/`：DeepSeek 空输出问题的受控诊断和恢复证据；这些不计入原始矩阵的额外格数。
- `experiments/*usage*.jsonl`：正式矩阵、早期 pilot 和诊断调用的用量审计日志；pilot 的临时性能表与摘要已清理。
- `report/project_report_en.pdf`、`.docx`、`.md`：英文正式实验报告及可编辑源稿，供课程提交。
- `report/实验报告.pdf`、`.docx`、`.md` 为同步修订的中文报告。

## 结果摘要

原始生成实验覆盖 30 题 × 2 模型 × 2 种策略。Pi 关闭工具并只生成一次，自研策略允许两轮编译反馈修复。两组比较反映这两种具体策略的表现。题库 v1.1 的新规约未用于原始源码生成。

 统一离线复测覆盖全部 120 份归档最终源码。52 份通过、3 份被 CODESYS 拒绝、65 份因缺少结束标记或注释未闭合被完整性检查拒绝。120 份源码哈希均一致。历史 90/120 和 30/30 属于旧项目构建记录，不能用于当前编译判定。 见 `experiments/linked_compile_review/`。

历史运行验证中，P02 的四份输出共通过 20/20 STruC++ 扫描测试，四份 STruC++ 翻译代码共通过 918 项 CBMC 有界性质。自研 Agent × GPT/DeepSeek 的 112 个场景向量共计划 224 个模型-场景执行，实际在 Control Win 执行 88 项（82 PASS、6 FAIL），覆盖 56 个不同场景 ID。20/60 份候选输出全场景通过，3 份有 runtime 断言失败，37 份未完成 runtime（12 份正式离线编译失败、25 份集成工程编译失败）。PLCVerif 未运行；结果不能表述为全数据集 runtime 通过。

历史项目 API usage 合计 ¥6.099742，低于当时授权上限 ¥18。该费用不是未来运行报价。API key 未包含在提交物中；重跑模型实验需操作者自行设置 `DMXAPI_API_KEY` 并指定预算上限。

## 从仓库运行

克隆后可先做不产生 API 费用的本地检查：

```powershell
git clone https://github.com/yedou37/plc-st-codegen-agent-assignment.git
Set-Location plc-st-codegen-agent-assignment
py -m unittest discover -s tests -v
```

Pi 基线还需 Node.js 22.19+ 和 `npm ci`；STruC++、CBMC、CODESYS 编译和新模型实验各自需要额外工具。完整安装和命令见 [`docs/REPRODUCING.md`](docs/REPRODUCING.md)。

## 数据与解释边界

- 当前离线指标为 52/120。旧状态供追溯。
- CODESYS PASS 代表离线项目编译，不代表 PLC 下载、扫描仿真、I/O 映射正确或现场功能通过。
- runtime 报告区分 112 个场景 ID、224 个模型-场景执行计划、88 个实际执行场景以及 136 个阻塞场景；82/88 是已执行子集的通过率，不是全矩阵通过率。
- 918 项 CBMC 检查是对 P02 的 STruC++ 翻译代码作有界检查，不是对全部 ST 或全部 LTL 的证明。
- usage JSONL 记录模型、token、费用、耗时、状态和时间；不保存 key、prompt 或响应正文。
