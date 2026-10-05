# 修复源码与验收证据交付

这两个 ZIP 合起来提供本轮 P1 覆盖、正式 gate 和多种子保存资源验收所需的源码与数据。它们不是整个历史工作区的逐字节全量备份。原始 FAIL、旧代表预检和中间修复证据仍保留，并与新全候选 P1 分开。

## 解压与组合

将源码 ZIP 解压到 `source/`，证据 ZIP 解压到 `evidence/`。先按各包根目录 `FILE_MANIFEST.csv` 验证文件。不要把两个同名清单互相覆盖。

在两目录的上层执行：

```powershell
python -X utf8 -B source/scripts/assemble_acceptance.py --source source --evidence evidence --output assembled
Set-Location assembled
$session = Get-Content P1_PACKAGING_SESSION.json -Raw | ConvertFrom-Json
python -X utf8 -B scripts/check_p1_coverage.py --source results/multiseed_20260918T163717Z --run $session.full_run --strict --output extracted_p1_check.json --csv extracted_p1_check.csv
python -X utf8 -B scripts/multiseed_experiment.py --help
```

`assemble_acceptance.py` 按 `DUPLICATE_FILE_MAP.csv` 从两包中的实际相同字节恢复重复路径并校验 SHA-256。原 run 的冻结输入、实例/候选清单、任务清单、保存资源和 raw/digest 数据都在两包内；上述检查无需基础 ZIP 或旧机器绝对源码路径。

`BASE_FILE_MANIFEST.csv` 是旧快照的原始清单。每个 ZIP 自己的 `FILE_MANIFEST.csv` 是本次包内清单，两者用途不同。`CHANGE_MANIFEST.csv` 以旧清单为基准，包含新增、修改、删除及哈希。

## 实验与环境

覆盖检查只需要 Python、NumPy。`$session.full_run/requirements-p1-lock.txt` 来自本次实际运行的 Qiskit 2.5.2 解释器；其他实际环境锁文件位于 `corrections/review_v2_20260920/requirements-*-lock.txt`。共享环境未修改。全新环境安装未验收，不应将现有环境运行成功称为干净重建成功。

如需要重新执行全候选 P1（不是解压验收的必要步骤），选用匹配版本环境：

```powershell
python -X utf8 -B scripts/prepare_full_p1.py --source results/multiseed_20260918T163717Z --output corrections/my_new_full_p1
python -X utf8 -B scripts/multiseed_experiment.py --stage p1 --run-dir corrections/my_new_full_p1
```

这只执行两个指定实例的全部候选预检，不运行 101,460 条正式任务。不要复制两个 repetition 的观察记录；每条结果包含独立 worker 观察 ID。代表模式必须显式使用 `--p1-scope representative`，不能满足正式 gate。

源码包包含完整测试源码、配置、schema 和精简数据。已有完整依赖环境可执行：

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B golden_example/run_tests.py
```

## 省略的大文件与历史基础包

`OMITTED_LARGE_FILES.csv` 逐个列出超过 50 MiB 的省略文件、用途、字节数、哈希、生成命令和依赖。原始编译资源没有省略；省略的是可再生的巨大预算明细，以及不用于本轮验收的旧冗余/中断临时表。需要巨大修正预算明细时，从两包中的保存资源运行分析到新目录即可生成，不重新编译量子电路。

`BASE_ARCHIVE_REQUIREMENTS.json` 明确了需要原基础包的额外历史检查：逐字节恢复被省略的旧巨型文件、整个旧工作区保全重查和不在本轮交付内的历史管线材料。完整覆盖核对、修正数值核验、相对路径入口和正式 P1 gate 的读取检查不依赖该基础包。

## 验收证据

`EVIDENCE_INDEX.json` 将 R1–R12、完整 P1、测试、原始保全和有限重放关联到相对路径。最终包的 SHA-256 在外置 `SHA256SUMS.txt`；实际 ZIP 重新解压的 CRC、路径安全、逐文件哈希、依赖解析和入口检查结果在外置 `PACKAGE_VALIDATION.json`。不将 ZIP 自身的哈希放入 ZIP 内，避免循环依赖。

论文 PDF 编译、最终稿采纳、全新环境安装、heavy-hex 53/54 仍为 BLOCKED/未验收。本交付没有 commit、push、merge 或 Release。

R12 closeout: latest paper/source binding is corrections/review_v2_20260920/closeout_20260921T130854186Z_0458abb8/PAPER_ARTIFACT_MAP_v2.json. The original PAPER_ARTIFACT_MAP.json remains historical. Build using scripts/package_repair_acceptance.py --session corrections/review_v2_20260920/closeout_20260921T130854186Z_0458abb8/P1_CLOSEOUT_PACKAGING_SESSION.json. Verify the map with scripts/build_paper_artifact_map_v2.py --verify.


