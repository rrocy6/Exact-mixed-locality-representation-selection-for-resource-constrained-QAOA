# URSS：完整代码与已核验的本地实验结果

统一交付分支：`delivery/urss-code-results-20260913`。

D01–D08 的代码修正、必要重跑和结果审计已完成。最新实验代码为 `fa5bbbbb0644b007176fe5727d36f66b969e5c8b`，包含 QAOA 的 `bcf47285d474a4bffb863984340978aa10816f80` 及更早的选择器和 warm-start 修正。本次整合另外修复了 QAOA 论文片段生成器：从结果表读取实际均值和区间，并通过输入摘要关联 E2/E5 完成状态。实验计算代码和原始结果没有改变。

## 当前结果入口

| 内容 | 原始归档或索引 | 核验结果 |
| --- | --- | --- |
| 最初 warm-start 坐标修正 | [完整原始 ZIP](delivery/20260913/archives/URSS_WARMSTART_CORRECTION_EXECUTED_v1.zip) | 4,800 个任务，4,332 项重跑和 468 项有效复用；60 个主要比较重建一致 |
| Windows 选择器修复后 QAOA | [本地 QAOA ZIP](delivery/20260913/archives/URSS_QAOA_LOCAL_RESULTS_20260913_010958_585.zip) | 420 次优化，492 条新观测 |
| Windows E2/E5 | [本地 E2/E5 ZIP](delivery/20260913/archives/URSS_E2_E5_LOCAL_RESULTS_20260913_020457_389.zip) | 7,125 条资源记录；272 个主实验和 324 个附加 E5 端点 |
| 文件大小与 SHA256 | [ARCHIVES.json](delivery/20260913/ARCHIVES.json) | 三个 ZIP 均保持上传时的原始字节 |
| 独立结果检查 | [INDEPENDENT_VERIFICATION.json](delivery/20260913/audits/INDEPENDENT_VERIFICATION.json) | 原始任务、重跑检查点、历史字段保留和跨包依赖 |
| 当前汇总表及图表 | [summaries](delivery/20260913/summaries)、[paper_materials](delivery/20260913/paper_materials) | 直接取自或重新生成于已核验的 Windows 结果 |
| 逐项完成情况 | [CODE_CLOSEOUT.json](delivery/20260913/CODE_CLOSEOUT.json) | 代码执行状态与论文、作者声明分开记录 |

新结果使用原始数据中的既定实例、种子、预算和统计规则。4,695 条新资源记录为预期宽度限制，不是意外编译失败；不得填补为成功资源或零成本。QAOA 的 E6 三个噪声等级共 442,368 shots。

## 检查交付内容

在仓库根目录，使用运行实验时的 Python 3.12 环境执行：

```powershell
python -X utf8 -u verify_final_delivery.py --repo . --json-output "$env:TEMP\URSS_DELIVERY_VERIFY.json"
```

该命令重建审计与统计量，不执行新的 QAOA 优化或硬件编译。固定依赖见 [requirements-delivery.txt](requirements-delivery.txt)。完整原始 ZIP、内层文件清单、检查点及冻结源码都保留在归档中；当前 CSV 的位置可由 ZIP 内的 `COVERAGE.csv` 和 `EXECUTION_AUDIT.json` 追溯。

需要从解压的 Windows 结果重新生成 QAOA 图表时：

```powershell
python -X utf8 make_selected_qaoa_paper_updates.py --output "QAOA结果解压目录" --resources-output "E2_E5结果解压目录"
```

在原始 ZIP 的副本中生成衍生材料。原始 ZIP 和审计文件保持不变。

## 历史版本与当前状态

- `corrections/review_closeout_v2/REPLAY_EVIDENCE.zip` 保留选择器 1,212 项检查、影响审计及更早重建证据。
- `four_part_addendum_v1/`、`fibre_e1_e6_v2/` 和早期 `results/` 保持各自历史含义；当前受影响记录以本页列出的两个 Windows 结果包为准。
- 旧审计中的 `PENDING` 或 `NOT_PUBLISHED_BY_THIS_RUN` 是其生成时状态。用当前完成索引及上传脚本生成的远程核验回执判断后续工作，不改写历史证据。
- 旧分支对应的提交保留为版本标签。上传脚本只允许普通快进更新 `main`；出现分歧或分支保护时，提交统一交付分支供审查，保留已有主分支内容。
- GitHub 上传与 Overleaf 相互独立。仓库中的 `paper/` 是历史源码；当前 Overleaf 全文合并尚未完成。资助、作者贡献、利益冲突和最终软件许可仍由作者确认。

## 本地上传与远程验证

使用配套的 `URSS_GITHUB_FINAL_UPLOAD_v5.zip`。其中的启动脚本复用已完成 E2/E5 会话的 Git 仓库和 Python 环境，导入已审核提交，上传主分支、统一交付分支及历史标签，然后从远程重新获取三份归档并验证 SHA256。

成功标记：`ALL LOCAL RESULTS UPLOADED + REMOTE VERIFY: PASS`。只有收到该标记及 `UPLOAD_RECEIPT.json`，才认定本地结果已经上传；本地打包或生成提交本身不代表远程成功。
