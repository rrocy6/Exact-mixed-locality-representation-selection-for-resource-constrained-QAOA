# 使用说明

1. 阅读 `PLAN.md`。本包只固定计划及检查输入，没有正式QAOA重跑入口。
2. `EXPERIMENT_PLAN.json` 为结构化实验约定；不得直接传给旧addendum runner。
3. `EXPECTED_RUNS.csv` 包含480个targeted和4,320个原始E4任务；任务以完整组合及task_id标识。
4. `SOURCE_INPUT_MANIFEST.csv` 固定82个基线输入，不包含尚未绑定的本机修复代码。
5. `SHA256_MANIFEST.csv` 和sidecar记录本计划包文件完整性。

在Windows PowerShell的项目根目录中，假设将本包目录放在 `plans/URSS_warmstart_correction_plan_v1/`，使用项目现有虚拟环境：

```powershell
python .\plans\URSS_warmstart_correction_plan_v1\verify_plan.py --repo .
```

命令只读：核对文件字节hash、实验task的唯一性、完整覆盖、seeds和冻结字段，不修改旧结果，不运行QAOA。

`input_plan_check: PASS` 仅表示计划/来源检查通过；`execution_binding` 仍为PENDING，因为脚本不验证或伪造修复代码和null-control证据。正式运行前由执行器写独立 `EXECUTION_BINDING.json`，绑定本机修复版本、环境、null-control证据和冻结的编码/概率。

若hash不符，先定位是不是旧版本、错误目录或换行差异。不要自动重写已有归档或重新计算hash来掩盖来源差异。

旧strong-bias runner会重新进行候选筛选。本计划要求恢复原冻结输入后直接运行固定任务，因此不要用更换output-root的方式代替专用的冻结输入重跑入口。
