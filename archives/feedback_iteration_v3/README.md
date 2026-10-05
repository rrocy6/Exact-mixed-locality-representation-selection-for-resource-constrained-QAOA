# URSS Feedback 2/6 实验迭代 v3

这是独立的新增实验，不覆盖 v1/v2 的 `payload`、论文和原结果。协议及科学执行/分析代码在新实例生成前冻结。完整运行数据与审核一起交付。

## 实验问题

1. 在同一实例、同一实际电路和预先指定的资源预算下，选出的 mixed 表示是否达到解质量目标，而选出的 native/full 未达到？
2. 在完全相同的 proper-mixed 候选库中，无 guardrail、raw-moment guardrail、prepared-state guardrail 对可选候选、最终质量和辅助位一致性有何影响？

主预算为物理占用 Q<=12、CX<=96、CX 深度<=64、最大 penalty<=16；主质量目标为归一化目标差 <=0.2。另有事先固定的 432 个资源组合和三个质量阈值作为描述性敏感性分析，不把预算格当作独立样本。

每类 30 个新随机实例；另有 12 个结构化机制实例，不合并统计。Guardrail 阈值固定为 0.02，无候选时记录不可用，不放宽阈值或补入未通过的候选。性能测试采用同起点同预算 Nelder–Mead，并对预先指定的关键选择执行 65x65 参数网格与四次局部细化。

## Windows 使用

依赖沿用此前已验证的 `revisions/URSS_20260917_verified_v1/.venv_revision`。下载 ZIP 至 Downloads，在原项目根目录打开 PowerShell：

```powershell
$kit = Join-Path $env:USERPROFILE 'Downloads\URSS_Feedback_Iteration_v3'
Expand-Archive -LiteralPath "$kit.zip" -DestinationPath $kit -Force
& "$kit\RUN_ITERATION.ps1" -Command verify -ProjectRoot (Get-Location).Path
```

以上核验包内已执行结果，并在原项目的新检查目录写 JSON。它不重新优化全部实验。

从头在 Windows 执行：

```powershell
& "$kit\RUN_ITERATION.ps1" -Command run -ProjectRoot (Get-Location).Path -Workers 4
```

命令输出本次 `RUN_DIRECTORY`。随后指定该目录核验和分析：

```powershell
& "$kit\RUN_ITERATION.ps1" -Command verify -RunDirectory '刚输出的完整运行目录'
& "$kit\RUN_ITERATION.ps1" -Command analyse -RunDirectory '刚输出的完整运行目录'
```

中断后用相同环境与范围续跑：

```powershell
& "$kit\RUN_ITERATION.ps1" -Command run -RunDirectory '原运行目录' -Resume
```

完成实例的哈希不一致会拒绝跳过；未完成实例重新计算。`RUNNING.lock` 为保留的系统锁文件，进程退出自动释放锁。无需删除它。

Python 直接入口：`python study.py run --output NEW_DIRECTORY --workers 4`、`python audit.py --run RUN_DIRECTORY --output NEW_AUDIT.json`、`python analyse.py --run RUN_DIRECTORY --output NEW_ANALYSIS.json`。

## 文件与解释

- `protocol.json`：预算、质量目标、种子、候选库、统计规则及验收条件。
- `freeze.json`：冻结时间、科学源码哈希和运行环境；这是本地记录，不是外部注册。
- `execution/results/`：每实例候选、实际编译资源、诊断、选择结果、参数轨迹和经典对照。
- `execution/grids/`：完整 65x65 参数网格。
- `execution/completed/`：实例完成标记和文件哈希。
- `analysis.json`、`audit.json`：科学结果与独立数值验收，两者不能互相替代。
- `URSS_Feedback_Iteration_v3_Report.md`：中文结论及对第 2/6 条的回应。
- `paper_addendum.tex`：可审阅的英文论文补充段落，不自动改动 Overleaf。
- `vendor/`：单独复制并冻结的既有数值/编译辅助函数；此次执行逻辑在 `study.py`。
- `historical_signatures.json`：与提供的历史材料对照所需的目标签名；不声称覆盖未提供的数据。

`audit.json` 的 PASS 代表计算和记录检查通过，不代表实验一定支持 mixed 或 guardrail 优势。两个端点未通过若仅针对有限搜索选出的表示，不得写成“所有端点实现都不可能”；只有完整的逻辑宽度/penalty 枚举排除才标记资源证书。经典 rounding/sampling 的结果必须与 QAOA 一起解释。

本次真实运行平台为 Linux。Windows 脚本复用相同 Python 实现，但其 PowerShell 包装器尚未在真实 Windows 上运行。
