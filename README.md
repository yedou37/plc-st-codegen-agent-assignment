# PLC Structured Text 代码生成大作业

本项目依据课程大作业要求，包含 30 题 Structured Text 数据集、自研 PLC 代码生成 Agent、四条件模型实验、生成源码、CODESYS 编译与 runtime 测试、P02 自动化测试与有界验证，以及实验报告。本文说明项目目标、结果、目录结构和运行入口；完整环境配置与复现命令见 [`docs/REPRODUCING.md`](docs/REPRODUCING.md)，Agent 实现约定见 [`AGENTS.md`](AGENTS.md)。

## 项目结果与验证范围

- 数据集共 30 题：20 道给定题、10 道原创题；包含接口、假设、207 条 scan-level LTL 规约和 112 个测试场景。
- 统一离线复测覆盖全部 120 份归档最终源码。52 份通过、3 份被 CODESYS 拒绝、65 份因缺少结束标记或注释未闭合被完整性检查拒绝。120 份源码哈希均一致。历史 90/120 和 30/30 属于旧项目构建记录，不能用于当前编译判定。 [逐格结果和诊断](experiments/linked_compile_review/README.md)。
- Pi 关闭工具并只生成一次，自研策略允许两轮编译反馈修复。两组比较反映这两种具体策略的表现。题库 v1.2 的规约未用于原始源码生成。
- P02 的四种输出通过 STruC++ 测试 **20/20**；相应翻译代码通过 CBMC **918 项性质**。这些补充验证的题目范围为 P02；全数据集的 207 条 LTL 规约保存在题目数据集中。
- **历史 CODESYS runtime 场景测试：** 自研 Agent × GPT/DeepSeek 共 60 份输出，计划执行 224 个模型-场景组合；实际执行 88 个（82 PASS、6 FAIL），覆盖 56/112 个不同场景 ID。20 份输出的全部场景通过，3 份存在断言失败，37 份因编译问题未进入完整 runtime 执行（12 份正式离线编译失败，25 份集成测试工程编译失败）。逐题结果见 [`experiments/codesys_validation/self_agent_runtime_20261110.md`](experiments/codesys_validation/self_agent_runtime_20261110.md)。
- **CODESYS IDE 模拟复测：** 51 份原始源码实际执行 199 个场景组合，195 PASS、4 FAIL，覆盖 19 道题和 72/112 个不同场景 ID。48 份输出通过各自的全部场景。P05、P14 的三份人工修订另通过 9/9 个场景。 [逐格实测记录](experiments/ide_simulation_review/README.md)
- **LTL 验证范围：** 数据集提供 207 条 scan-level LTL 规约；CBMC 有界检查覆盖 P02 的四种输出，PLCVerif 未纳入本项目验证。
- DeepSeek 修复前后的实验和调用费用记录保留在 `experiments/`，但不保留 prompt、模型响应正文或 API key。

完整验收判断见 [`验收对照表.md`](验收对照表.md)，提交内容清单见 [`README_提交说明.md`](README_提交说明.md)。英文正式实验报告见 [`report/project_report_en.pdf`](report/project_report_en.pdf)；可编辑版本和 Markdown 源稿也一并提供。中文报告保留在 `report/`。

## 快速开始

下面的本地数据集检查不需要 DMXAPI 密钥、Node.js、CODESYS 或外网 API：

此仓库为私有仓库，克隆前需获得仓库访问权限。

```powershell
git clone https://github.com/yedou37/plc-st-codegen-agent-assignment.git
Set-Location plc-st-codegen-agent-assignment
py -m unittest discover -s tests -v
```

Python 3.10 或更新版本即可运行 Python 检查脚本；项目不需要额外 pip 包。要运行 Pi 基线，需安装 Node.js 22.19+ 和锁定版本的依赖：

```powershell
node --version
npm ci
```

按需检查 STruC++、CBMC 和 CODESYS 的完整步骤见 [`docs/REPRODUCING.md`](docs/REPRODUCING.md)。

## 仓库导航

| 路径 | 内容 |
|---|---|
| `dataset/` | 题库、标准化的 30 题、原创题来源及重建脚本 |
| `src/` | 自研 Agent、模型 API 适配器、ST 静态检查与提示词 |
| `st/runs/` | 正式矩阵生成的 ST 输出和对应编译日志；`attemptN` 保留自研 Agent 的修复尝试 |
| `st/support_types/` | P07/P17 需要的题目定义 DUT |
| `experiments/results.csv` | 原始 120 格正式矩阵 |
| `experiments/codesys_validation/` | 正式矩阵超时重试、P02 runtime 冒烟与自研 Agent runtime 场景汇总 |
| `experiments/ide_simulation_review/` | 51 份原始源码的 IDE 模拟断言和 3 份人工修订 |
| `experiments/posthoc_repair/` | 30 个原始 FAIL 的修正适配器复测证据 |
| `experiments/functional_tests/` | 四个 P02 STruC++ 运行结果 |
| `experiments/formal_verification/` | 四个 P02 的 CBMC 输入、日志和结果 |
| `experiments/diagnostics/deepseek/` | DeepSeek 空输出诊断、参数 smoke 和恢复结果；不并入原始矩阵 |
| `tests/` | Python 检查、ST 测试模板及 CBMC harness |
| `tools/` | 运行、编译、复测、报告和打包脚本 |
| `report/` | 最终报告的 Markdown、DOCX 和 PDF 版本 |
| `验收对照表.md` | 作业验收项与证据映射 |

`experiments/README.md` 解释正式证据、诊断记录和本地新运行的区别。
`experiments/*usage*.jsonl` 保存正式矩阵、pilot 和诊断调用的 usage 审计日志。
