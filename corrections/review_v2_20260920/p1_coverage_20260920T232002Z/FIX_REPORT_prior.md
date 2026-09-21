# R1–R12 实际修复与验收报告

本轮在 `URSS_REPAIR_WORKSPACE_20260920/project` 内实际修改源码、执行测试和重建分析。原始实验、冻结配置、历史 FAIL 审计和原论文均未覆盖；没有 commit、push 或 Release，也没有重跑全部 101,460 次编译。

正式修正产物：`corrections/review_v2_20260920/final_analysis/`。中间分析、失败测试日志及首次重放入口错误日志也保留在同一 correction 版本目录中，不作为最终验收依据。

## 已执行的验收

| 验收 | 实际结果与证据 |
|---|---|
| 原报告独立复算脚本 | 从同级 review 复制到 project 内执行，避免向 review 写文件；`evidence/recheck_results.json`：1,800 数组、37,661,400 单元零差异 |
| 修正产物独立复算 | `scripts/verify_multiseed_correction.py` 不调用生产分类/selector 函数；1,800 数组、1,800 selector 行、稳定性标签、图表 CSV、YAML 全部通过；`evidence/correction_verification.json` |
| 数值结论 | **79,069 / 149,439 = 52.910552131639%**，两次独立完整向量复算均得出此值，无硬编码回填 |
| 最终数据审计 | `final_analysis/AUDIT.json`：101,460 个自然键完整且唯一，compiled=101,460、failed=0、UNKNOWN 单元=0、postprocess_complete=true |
| 仓库测试 | 最终 187/187 PASS；`evidence/full_tests_acceptance.log`。其中相关回归 21 项，覆盖真实入口和进程超时 |
| Golden | 10/10 PASS；`evidence/golden.log` |
| 匹配环境正式 worker 重放 | Qiskit 2.5.2 / NumPy 2.5.3 / SciPy 1.18.1；预先选择 108 任务，编译、callback、有限角度语义和重复性通过，Q/G/D/M/J 相对历史零差异；`replay/REPLAY_REPORT.json` |
| 新 P0→P1 CLI | 新目录冻结配置并执行另 108 条有限预检，PASS；`preflight_new/P1_REPORT.json`。没有执行该新 run 的正式全量编译 |
| 历史保全 | 对原清单中 results/audit/configs/evidence 下 4,216 个文件复核，零改动；`evidence/PRESERVATION_CHECK.json`。原清单内改动仅三个研究脚本 |

上表 evidence、replay、preflight_new 路径均相对 `corrections/review_v2_20260920/`。

## 逐项修复

| 项目 | 实际修改 | 验收 / 剩余限制 |
|---|---|---|
| R1 审核、缓存恢复 | 新增共享 `multiseed_validation.py`，按自然键核对覆盖和唯一性、终态、资源、J、来源及 digest/trace 链；正式恢复、batch 写入、汇总和 audit 接入。统一新 task ID，保留旧 ID 的显式映射。分开报告覆盖、编译失败和后处理；验收不满足时 CLI 非零退出 | PASS。缺失、重复、额外任务及 running/pending 污染缓存均被拒绝；真实 101,460 行通过。旧保存 digest 关联不等于重新证明电路内容 |
| R2 P1 | 校验每个预期任务、两个 1729 重复和 2718 的完整性；报错、超时和非法资源不得 PASS；宽度排除需证据。固定预检代表选择规则；记录配置/输入/编译实现身份与预检行哈希；新增正式任务前强制校验匹配 P1 | PASS。四类失败反例和有效重复通过回归；新 P0→P1 的 108 条真实任务通过。P1 为有限代表预检，非全库电路证明 |
| R3 配置身份、完整 YAML | 读入重算配置哈希；核验快照及冻结源码；历史 manifest 绑定原归档清单，新配置绑定 candidate/sample/input-copy 清单；执行 trials 从配置读取，不支持的网格/拓扑/布局/线程协议显式拒绝。编译身份独立于后处理身份，旧资源可分析，新任务不得冒用旧编译身份。输出完整 JSON 兼容 YAML | PASS。配置篡改和实现身份变化被拒绝；历史 run 正常读入；完整 YAML 反序列化与 JSON 相等。P0 忽略上层 Git 仓库 |
| R4 稳定性 | 独立输出 `lost_in_any_other_seed`、`lost_in_all_other_seeds`；stable 定义为全部基准点保留，空基准单列 | PASS。分别为 70,370 和 13,779；171 partial、35 disappeared、49 stable、105 empty_baseline；654→36 正确归入 partial；交集仍 79,069 |
| R5 baseline selector | 每个 setting 显式固定 1729 的最小 J winner；在其完整可行预算集合上逐 seed 复算覆盖，保留资源 task ID；重选 winner 单列，缺记录 UNKNOWN，零分母 N/A | PASS。1,800 行独立复算零差异；覆盖 winner 改变但基准仍可行、部分覆盖丢失和记录缺失反例 |
| R6 逐 seed 图 | 图的定义统一为非空 TRUE setting 比例，由各 seed 明细生成 CSV 与 SVG | PASS。各 seed 分子为 255、255、262、254、256，分母均 360；回归验证每根柱使用对应 seed；旧图保留 |
| R7 容量排除 | 正式分类与 core 复用容量证据规则；仅冻结逻辑宽度 >12 时认可 width_exceeded；无证据则 UNKNOWN | PASS。mixed 可行且 full 有可信宽度排除时 TRUE；伪造/缺少宽度证据不能认证 TRUE；历史数据无此状态 |
| R8 非法资源 | 资源入口检查有限、非负、Q/G/D 整数、物理宽度和 J；审计拒绝非法行，分类将非法证据保留 UNKNOWN | PASS。NaN、Inf、负值、非整数、越界 Q 回归通过；真实保存资源无非法值 |
| R9 真正超时 | 新增可终止独立任务进程调度，计时从 Process.start 前开始（含启动开销），到期 terminate/kill、保存 timeout，退出清理仍运行的进程；正式与 P1 路径均使用 | PASS。实际进程超时回归通过；真实 P1 已走此调度；已有 batch 不覆盖，重试须新目录 |
| R10 实际 trace | 正式 worker 接 callback，记录实际 pass 和 SABRE 参数，拒绝未声明布局搜索；声明字段与观测字段分开 | PASS。匹配环境的有限重放及 P1 均使用该 worker；历史手填 trace 仍明确标为 declared-only，不追溯改写为 observed |
| R11 正式语义入口 | 正式 worker 的 P1/重放调用 `verify_formal_semantics`：按冻结多项式计算期望相位，校正最终 routing permutation，在两组固定角度核验 | PASS（有限验证范围）。108 重放与 108 P1 编译/语义检查通过；不是对 101,460 个历史电路、所有参数或所有输入态的完整证明 |
| R12 论文、环境、产物映射 | 新增可运行分析/核验/论文构建入口，实际环境锁文件和 `README_REPRODUCE_REPAIRS.md`；CSV 驱动论文表；保存 `main_repaired.tex` 副本，`PAPER_ARTIFACT_MAP.json` 映射原 run→修正版本→表图→论文 SHA-256 | 产物生成 PASS；最终出版验收部分 BLOCKED，见下 |

核心修改是 `scripts/multiseed_experiment.py`、`multiseed_compile.py`、`multiseed_core.py`；新增共享校验、调度、独立产物核验、正式重放与论文映射脚本，以及 `tests/test_multiseed_repairs.py`。正式资源只读取和复制，后处理采用流式写出大预算明细以避免累积数百万行字典。

## 保留的失败记录与剩余问题

- 初始默认环境的测试有 31 ERROR，主要是沙箱临时目录/进程管道限制与缺少 reportlab；日志保留。改用已有完整依赖环境并允许真实本地测试进程后，最终全部通过。没有把这些环境错误算成 PASS。
- 首次有限重放在相对路径处理处退出；已修复 `load_run` 的路径归一化。失败日志 `evidence/replay.log` 与后续成功日志 `replay_attempt2.log` 均保留。
- **BLOCKED：论文 PDF 编译。** 当前找不到 pdflatex/latexmk；已生成 TeX 副本和表图映射，未伪称 PDF 编译通过。
- **BLOCKED：最终论文采纳/发布身份。** 未提供另一个已采纳最终稿的版本；现有论文其他小节仍有 TODO。映射只将 `main_repaired.tex` 标为待审阅修正版，不把它当作最终 Release。
- **BLOCKED：全新环境安装复现。** 已读取并实际使用匹配历史版本的现有环境，导出完整 pip freeze；未执行从包源全新安装这些精确版本，不能声称干净环境重建已验收。不同用途的环境锁文件分开保存。
- 报告提及的其他历史研究结论（例如 53/54 heavy-hex）不在本轮有限多种子核验范围；未新增或背书该数字。本轮科学结论限于冻结候选、三种拓扑、两种 synthesis 和五个固定 seed。

复现命令与限制见 `README_REPRODUCE_REPAIRS.md`。最终交付不包含任何 Git 提交、推送或 Release 操作。
