# Warm-start 坐标修正：执行结果

执行：`exec_20260912_v2`；冻结计划 v1。全部 4,800 个任务已完成，4,332 个重新优化，468 个零层初态验证复用。

Targeted Max-3SAT 相对 cold 的改善保留；原始 E4 的主要 pair−cold 对比均未形成排除零的 95% 区间。这里的“未明确”不等于无效或等效。

| 研究 | Family | 预算 | 实例 n | pair−cold 均值 [95% CI] | 含零层实例 |
|---|---|---|---:|---|---:|
| original_e4 | Spin glass | B=128 | 2 | -0.2222 [-3.0458, 2.6014] | 2 |
| original_e4 | Spin glass | B=256 | 2 | 0.0374 [-2.3424, 2.4173] | 0 |
| original_e4 | Spin glass | p=1 | 2 | -0.0037 [-8.1718, 8.1644] | 0 |
| original_e4 | Spin glass | p=2 | 2 | -0.0915 [-0.2520, 0.0690] | 0 |
| original_e4 | Max-3SAT | B=128 | 7 | -0.6768 [-1.9673, 0.6136] | 2 |
| original_e4 | Max-3SAT | B=256 | 7 | -0.6218 [-1.8792, 0.6355] | 0 |
| original_e4 | Max-3SAT | p=1 | 7 | -0.8717 [-2.0089, 0.2655] | 0 |
| original_e4 | Max-3SAT | p=2 | 7 | -0.8731 [-2.1540, 0.4078] | 0 |
| targeted | Spin glass | p=1 | 10 | 0.0028 [-0.2733, 0.2789] | 0 |
| targeted | Spin glass | p=2 | 10 | 0.1153 [-0.0468, 0.2774] | 0 |
| targeted | Max-3SAT | p=1 | 10 | -6.7198 [-9.2712, -4.1683] | 0 |
| targeted | Max-3SAT | p=2 | 10 | -6.7971 [-9.1395, -4.4547] | 0 |

## 解释边界

Targeted 每 family 固定 10 个 signal-enriched 实例，没有重新筛选或求 LP。Max-3SAT 的 original-only 与 independence 相对 cold 在 p=1、2 也均改善。Pair−original-only 在 p=2 为 −0.4759 [−0.8454, −0.1063]；p=1 的区间包含零。Pair−independence 在两个深度的区间都包含零，所以不能声称 pair moments 已显示稳定的额外收益。

原 E4 主表保留 selected active-aux 子集：spin glass n=2，Max-3SAT n=7。八组 pair−cold 区间都包含零。Max-3SAT 的 pair−original-only 在 p=2 为 −0.3108 [−0.5562, −0.0654]；这一探索性对比不能替代主要 pair−cold 结论。B=128 下 selected spin-glass 两个实例都是零层；Max-3SAT 有两个零层实例。全计划、正深度、零层统计分别见 analysis/。

所有区间先平均每设置的 3 个 restart，再平均原 5 个 matched draws（如适用），最后按 raw instance 配对；Student-t 自由度 n−1，未校正多重比较，两个研究不合并。主要比较只使用原始目标期望；encoded energy 等为诊断。

用同一实例级 Student-t 方法复算旧数据，原 E4 的八组主要 pair−cold 区间也都包含零。因此，旧表中基于其他区间算法的优势措辞不能直接沿用，亦不能把结论收紧全部归因于 mixer 修复。analysis/historical_paired_summary_same_statistics.csv 保留相同统计口径的旧结果。

## 执行与来源

真实执行代码的本地快照 commit：`1301a48c88d27ddc47c4fe10c547745d6fe28d9b`。这不是外部 GitHub 的已发布 commit。执行环境与 Windows 归档不同，因此全部正深度 cold 统一重跑。Targeted cold 新旧平均差 0.003939、最大绝对单行差 0.974304；不能把新旧优化结果变化全部归因于 mixer。

132 个冻结设计的 null-control 均通过；全部 4,800 条历史参数回放通过。实际误差见 CORRECTION_AUDIT.json。1541 个原包文件字节未变，仅先前两处 mixer/null-control 修复文件与原包不同。本次独立执行器和输出位于新目录。

首次绑定 v1 在任务数组读取处停止，未启动任何优化；保留原 binding、源码归档和 blocker。v2 修复入口并重新绑定后完成全部正式任务，没有按效果重试或删行。

## 论文交付状态

manuscript_snapshot/main.tex 是对上传旧快照的定点修改稿，包含 beta 坐标、warm-start Results/Discussion/Conclusion 和 provenance；同目录有差异补丁及原稿 hash。该快照其他实验结果仍是原有 TODO，不等同于当前 Overleaf 全文。warmstart_correction/ 内提供独立表图与文本，可按 LaTeX label 合入最新稿。尚未向 Overleaf 写入。

按新冻结计划，本轮不修改 kappa、Table 13 派生内容或 margin sensitivity；这些事项属于后续独立核验，未标记 PASS。LP 输入未变，因此 LP 信号图保留原版本。

独立的 4 页 correction_preview.pdf 已编译并检查排版。完整旧稿因缺少 quantumarticle.cls 未能编译；请提供最新 Overleaf 项目 ZIP（含该 class 和依赖）以完成正式合稿。
