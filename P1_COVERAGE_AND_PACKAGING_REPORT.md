# P1 覆盖与打包验收报告

项目：`C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/URSS_REPAIR_20260920_154042_4937f93c/URSS_REPAIR_WORKSPACE_20260920/project`。唯一运行后缀 `20260920T232002Z` 为 UTC 时间。修改、新结果和交付均限于此 project；上层 Git 仓库未修改、暂存或提交。

## 结论与计数

原方案第 5 节要求两个 family 的哈希首位实例、全部 topology/synthesis setting 的全部冻结候选。上轮 `preflight_new` 中的 108 是 **36 个 setting-specific 代表候选 × 3 次实际编译记录**，不是批次数、完整候选数或仅语义检查数。它有真实成功编译，但**不能满足完整 P1 gate**。另一个 `replay` 目录也是独立的 108 条有限代表重放，不计入本轮全候选 P1。

选择的旧报告是当前 project 的 `FIX_REPORT.md`：其 run 路径、108 行 CSV 和实际日志互相吻合；原文件及 SHA-256 保留于 `corrections/review_v2_20260920/p1_coverage_20260920T232002Z/FIX_REPORT_prior.md`，未覆盖。该报告中 R2 的代表预检 PASS 已由本报告的全候选验收取代，不能解释为原方案完整覆盖。

独立核验程序 `scripts/check_p1_coverage.py` 不导入生产 P1 任务生成器。它重算原 `instance_manifest.csv` 的 SHA-256 排序，选择 `max3sat_003`、`pair_star_isolated_025`，再取原 `candidate_manifest.csv` 的全部 setting-specific 候选，并逐项核对 input_hash 与冻结实例文件。

两个实例分别为 366 和 318 条冻结候选记录（三拓扑 × 两种 synthesis 各为 61 和 53），合计 **684**。每个候选独立执行 `1729/repeat_a`、`1729/repeat_b`、`2718/single`，由清单得到 **684 × 3 = 2052**。生产或验收代码没有把历史数量作为通过常量。历史原 P1 的实际 CSV 也独立核验为完整覆盖，见 `HISTORICAL_P1_COVERAGE.json`；其旧 trace/语义记录不替代修复后的正式路径验证。

| 覆盖 | 预期 | 实际 | 缺失 | 重复 | 额外 | 失败 |
|---|---:|---:|---:|---:|---:|---:|
| 上轮代表预检 | 2052 | 108 | 1944 | 0 | 0 | 0 |
| 本轮全候选 P1 | 2052 | 2052 | 0 | 0 | 0 | 0 |

本轮新增执行 **2052** 条，复用观察记录 **0** 条；可信容量排除 **0** 条。协议范围和编译观察实现升级，创建了新配置与派生关系，没有沿用旧哈希。旧 108 条记录没有复制来充当独立重复。每条新记录都有独立 observation_id、worker PID、开始时间、repetition 与单独 attempt_id；两个 repetition 不共享观察 ID。

## 实际实现与验收

- 默认 P1 恢复为全部候选；显式 `--p1-scope representative` 是 smoke，正式 gate 拒绝它，即使报告标为 pass。正式 gate 重新检查完整候选集合，而不是只相信报告计数。
- 新 P1 继续调用正式 `compile_batch_worker` 和真实 `multiseed_scheduler`；每个任务在独立可终止进程执行。计划在运行前冻结，逐批保存结果和失败证据。
- 684 条 repeat_a、684 条 repeat_b、684 条 single 全部编译成功。**2052** 条有实际 callback；资源合法、配置/输入/编译身份匹配；两次 1729 资源完全一致。
- 独立按完整 `(Q,G,D,M)` 向量重建两个 1729 的 12 个 setting 预算分类，并与生产报告逐数组哈希比较，零差异。完整预算覆盖与有限语义范围分开报告。
- 有限语义验证为预先选定的 **108** 条，使用两组固定角度；这不是全部电路、所有角度或所有输入态的证明。
- 相关回归 **27/27 PASS**，完整仓库测试 **193/193 PASS**，golden **10/10 PASS**。新增回归覆盖缺候选、缺 setting、缺第二次重复、重复 task、复制观察和代表子集伪装完整报告。
- `final_analysis` 的 101,460 行保存资源、raw/digest、覆盖和产物哈希重新只读核验通过。数值分析函数及独立核验源码相对上轮未变，复用且核验绑定的完整复算证据仍为 **79,069 / 149,439 = 52.910552132%**；不是硬编码回填。
- 原历史 results/audit/configs/evidence 中 **4216** 个文件再次核验，零改动。旧 108 条重放实际行、callback、语义和 Q/G/D/M/J 相对历史也重查通过；仅保留其历史实现身份，不冒充当前全候选 P1。

实际命令、UTF-8 日志、退出码和耗时在 `corrections/review_v2_20260920/p1_coverage_20260920T232002Z/`。全候选编译耗时约 698.5 秒；未执行正式全量 101,460 次编译或 QAOA。正式环境为 Qiskit 2.5.2 / NumPy 2.5.3 / SciPy 1.18.1；本次 pip freeze 位于 `corrections/review_v2_20260920/p1_full_20260920T232002Z/requirements-p1-lock.txt`，来自实际解释器而非手写版本列表。

## 最终证据与交付结构

- 最终 P1：`corrections/review_v2_20260920/p1_full_20260920T232002Z/`，含冻结派生配置、预先任务清单、逐任务 CSV、原始 batch JSON、环境、`P1_FULL_REPORT.json`。
- 覆盖前后：`corrections/review_v2_20260920/p1_coverage_20260920T232002Z/P1_COVERAGE_BEFORE.json`、`P1_COVERAGE_AFTER.json` 及对应 CSV；缺失/重复/额外自然键差集完整保留。
- 最终数值目录仍为 `corrections/review_v2_20260920/final_analysis/`，没有用中间 analysis 冒充最终结果。
- 交付目录：`C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/URSS_REPAIR_20260920_154042_4937f93c/URSS_REPAIR_WORKSPACE_20260920/project/delivery/repair_acceptance_20260920T232002Z`。
- 源码包：`URSS_REPAIR_SOURCE_20260920T232002Z.zip`；证据包：`URSS_REPAIR_ACCEPTANCE_EVIDENCE_20260920T232002Z.zip`。两包均使用相对路径、ZIP64 和各自的文件级 `FILE_MANIFEST.csv`。
- 外置 `SHA256SUMS.txt`、`PACKAGE_BUILD.json` 分别记录最终 ZIP 哈希及字节数；`PACKAGE_VALIDATION.json` 记录从实际最终 ZIP 重新解压的 CRC、路径安全、文件哈希、依赖恢复和入口执行结果。ZIP 自身哈希不内嵌，避免自引用。
- `CHANGE_MANIFEST.csv` 按旧 `BASE_FILE_MANIFEST.csv` 对比，不使用上层 Git 状态；`EVIDENCE_INDEX.json` 逐项映射 R1–R12。
- 巨型可再生预算明细和旧冗余/中断临时表的省略均列入 `OMITTED_LARGE_FILES.csv`，含用途、大小、SHA-256、命令、依赖。必要编译资源保留。重复输入/raw 等按 `DUPLICATE_FILE_MAP.csv` 从两包内相同字节重建，不依赖外部绝对源码路径。
- 两包联合足以重算 P1 覆盖、验证正式 gate 和保存资源；不是完整历史工作区备份。`BASE_ARCHIVE_REQUIREMENTS.json` 只为额外历史逐字节恢复注明原基础 ZIP 和 SHA-256。`DELIVERY_README.md` 给出相对路径组合与验收命令。

## BLOCKED / 未验收

论文 PDF 编译（无 LaTeX 工具）、最终稿采纳身份、全新环境安装仍为 BLOCKED；heavy-hex 53/54 未验收。本轮没有扩大处理这些投稿事项，也没有把有限语义检查说成全部历史电路证明。

未执行 commit、push、merge 或 Release；未重跑 101,460 条正式全量编译。包的最终重新解压验收以同目录外置 `PACKAGE_VALIDATION.json` 为准。

## 最终 ZIP 重新解压验收（包外补充）

最终两包重新解压验收 **PASS**。ZIP 内封存工程验收报告主体；本包外补充记录最终 ZIP 的字节数、哈希和之后完成的验收，避免循环绑定。

源码包：`C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/URSS_REPAIR_20260920_154042_4937f93c/URSS_REPAIR_WORKSPACE_20260920/project/delivery/repair_acceptance_20260920T232002Z/URSS_REPAIR_SOURCE_20260920T232002Z.zip`；5,221,267 bytes（4.98 MiB）；SHA-256：`790647bd9729479bc60f76d883531e7b5b547a85275825387e79f6c34b8229d1`。

证据包：`C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/URSS_REPAIR_20260920_154042_4937f93c/URSS_REPAIR_WORKSPACE_20260920/project/delivery/repair_acceptance_20260920T232002Z/URSS_REPAIR_ACCEPTANCE_EVIDENCE_20260920T232002Z.zip`；46,533,236 bytes（44.38 MiB）；SHA-256：`23921993b38b2c7ab392147e23382d7d1db7b739e89e228b15bc54c094598409`。

外部哈希：`C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/URSS_REPAIR_20260920_154042_4937f93c/URSS_REPAIR_WORKSPACE_20260920/project/delivery/repair_acceptance_20260920T232002Z/SHA256SUMS.txt`，227 bytes。

包装验收结果：`C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/URSS_REPAIR_20260920_154042_4937f93c/URSS_REPAIR_WORKSPACE_20260920/project/delivery/repair_acceptance_20260920T232002Z/PACKAGE_VALIDATION.json`，4245 bytes。两包 CRC、路径安全和全部 4,879 个清单文件哈希通过；另恢复并验证 7,703 个重复路径，联合目录包含 12,580 个文件。

解压后的相对路径入口、独立完整 P1 覆盖检查及生产 full gate 读取检查均通过，所有入口退出码为 0。实际命令和日志在交付目录的 `extracted_validation/`；这轮检查没有执行量子编译。

封包后发现复现说明的中文编码问题，已修正文档并重新封包；最终上述结果对应修正后的 ZIP 字节。前版 ZIP、文档和验收记录完整保留在 `attempt_before_document_encoding_fix/`，不作为最终交付。编译记录与科学产物未因文档修正而改变。
