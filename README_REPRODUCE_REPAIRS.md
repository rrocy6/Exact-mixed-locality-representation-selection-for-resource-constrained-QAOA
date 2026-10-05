> 完整 P1 的最新验收与交付见 `P1_COVERAGE_AND_PACKAGING_REPORT.md`、`DELIVERY_README.md`。旧 `FIX_REPORT.md` 中的代表预检 PASS 不等同于完整 P1。

# 复审修复版复现入口

修复说明见 `FIX_REPORT.md`。原始 `README_REPRODUCE.md`、`FILE_MANIFEST.csv`、历史 FAIL 审计和冻结 run 均保留，不能将旧清单当作修复版清单。当前 project 没有自己的 `.git`，P0 不再把上层仓库身份当作项目身份。

## 仅从保存资源复现（默认）

在本 project 根目录执行；需要 Python 3.12、NumPy、PyYAML。每次使用不存在的新输出目录。

```powershell
python -X utf8 -B scripts/multiseed_experiment.py --stage analyze --run-dir results/multiseed_20260918T163717Z --output-dir corrections/my_reanalysis
python -X utf8 -B scripts/multiseed_experiment.py --stage audit --run-dir corrections/my_reanalysis
python -X utf8 -B scripts/verify_multiseed_correction.py --source results/multiseed_20260918T163717Z --corrected corrections/my_reanalysis --output corrections/my_reanalysis_independent.json
```

分析从 101,460 条保存资源重建；不进行量子编译。审计将任务覆盖、编译成功、编译失败、后处理完成和科学 UNKNOWN 分开报告。缺失、重复、额外任务，非法资源或验收缺项导致非零退出。`TASK_ID_MAPPING.csv` 给出旧 manifest ID 与自然键规范 ID 的完整映射。

`stable` 仅表示所有基准 TRUE 点保留；不表示五个区域完全相同。空基准单列。selector 固定 seed 1729 的最小 J 候选，分母为该候选在完整预算网格中可行的点数，逐 seed 重算同一预算集合的覆盖；分母为零输出 N/A，记录缺失输出 UNKNOWN。图表 `region_presence_by_seed.svg` 的每根柱子来自同 seed 的非空 TRUE setting 数 / 360。

## 环境与有限正式路径验证

实际使用过的环境分别锁定在 `corrections/review_v2_20260920/requirements-*-lock.txt`：

- `formal-replay`：Python 3.12.10，Qiskit 2.5.2、NumPy 2.5.3、SciPy 1.18.1，与历史编译环境一致。
- `tests`：Qiskit 2.4.2，含 Aer、reportlab 等完整测试依赖；用于 187 项仓库测试。
- `analysis`：保存资源复算环境。分析不依赖 Qiskit，勿将其环境版本冒充历史编译环境。

用匹配环境的 Python 替换下列 `python`。可在项目内创建单独环境并根据对应锁文件安装；本轮验证了现有环境，未验证从公开包源全新安装这些精确版本，因此全新离线/在线环境重建仍为 BLOCKED（无安装验证证据）。不要用旧 `requirements-pilot-lock.txt` 的 Qiskit 2.4.2 冒充 2.5.2。

```powershell
python -X utf8 -B scripts/replay_multiseed_formal.py --source results/multiseed_20260918T163717Z --output corrections/my_replay
python -X utf8 -B scripts/multiseed_experiment.py --stage p0 --run-dir corrections/my_preflight
python -X utf8 -B scripts/multiseed_experiment.py --stage p1 --run-dir corrections/my_preflight
```

第一条是有限代表重放。P0→P1 默认行为已恢复为两个 family 哈希首位实例的全部冻结候选，分别独立执行 `1729/repeat_a`、`1729/repeat_b`、`2718/single`。任务数从候选清单推导，见 `P1_TASK_MANIFEST.csv`。旧 `preflight_new` 的 108 条只属于代表子集，不能满足正式 gate。显式 `--p1-scope representative` 仅用于 smoke，正式入口会拒绝其报告。均不自动启动 101,460 次全量编译。

P1 的每个可编译任务必须成功，且两个 1729 重复资源一致；2718 任务必须完整，容量硬排除必须有冻结宽度证据。语义验证直接走正式显式 SABRE worker，记录 callback 观测的 pass 和参数，在两个固定角度对所有计算基的对角相位进行叠加态检查并校正最终 routing permutation。此检查不是对历史全部电路内容的重新证明。

将来明确需要新正式编译时，`--stage run` 要求匹配的新配置、输入、编译实现和 P1 身份。任务超时从独立子进程启动前计时（含启动开销）；到期终止进程并保存 timeout，不在等待已完成 future 后才计时。已有 batch/预检证据不得覆盖；重试须新运行目录。历史完整缓存可只读核验、复制后分析；旧实现身份不能用于新增编译任务。

## 测试与论文映射

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B golden_example/run_tests.py
python -X utf8 -B scripts/build_repair_delivery.py
```

最后一条针对本次 `final_analysis`，要求独立核验与审计均通过，生成 `PAPER_ARTIFACT_MAP.json`、CSV 驱动的论文表和 `main_repaired.tex` 副本，并核验历史文件。原论文不覆盖。映射包含原 run、分析版本、表图、源代码和论文副本 SHA-256。

论文 PDF 编译目前 BLOCKED：没有可用的 pdflatex/latexmk。论文其他小节仍有原有 TODO；该副本是待审阅版本，不是已采纳或已发布的最终论文。本阶段没有 commit、push 或 Release。
