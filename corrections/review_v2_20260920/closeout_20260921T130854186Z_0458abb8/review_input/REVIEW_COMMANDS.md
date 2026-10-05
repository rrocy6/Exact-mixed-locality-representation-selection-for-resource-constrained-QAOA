# 本轮独立核验命令

在原两个 ZIP 验证并组合后的 `assembled` 目录运行以下命令。输出目录应单独新建，避免覆盖随包证据。下例以 `../review_outputs` 为输出目录。

```bash
python -B -m unittest discover -s tests -v > ../review_outputs/repository_tests.log 2>&1
python -B golden_example/run_tests.py > ../review_outputs/golden_independent.log 2>&1
python -B scripts/check_p1_coverage.py --source results/multiseed_20260918T163717Z --run corrections/review_v2_20260920/p1_full_20260920T232002Z --strict --output ../review_outputs/p1_independent.json --csv ../review_outputs/p1_independent.csv
python -B scripts/verify_multiseed_correction.py --source results/multiseed_20260918T163717Z --corrected corrections/review_v2_20260920/final_analysis --output ../review_outputs/numerical_verification.json
```

从本证据包所在目录运行补充只读检查，替换两个绝对路径：

```bash
python -B acceptance_checks.py --project /absolute/path/to/assembled --output /absolute/path/to/review_outputs/acceptance_checks.json
```

`acceptance_checks.py` 对每项检查分别记录结果，**请读取 JSON 中每项 status**；它保留 partial/findings，不以进程退出 0 代表全部验收通过。完整测试日志需要位于输出 JSON 的同目录。该脚本调用实际 gate/资源校验函数；独立覆盖与数值复算由上面两个不依赖生产分类生成函数的脚本完成。

本轮执行结果：仓库测试 exit 1（15 个缺依赖错误，两个 skip 事件，其中冻结 bundle 缺失使 5 个测试未运行）；Golden exit 0；独立覆盖 exit 0；独立数值复算 exit 0；补充读取检查完成且记录论文源码映射 partial。修复相关的 27 个测试均通过。

`input_identity.json` 记录原 ZIP 的独立哈希比对；`package_integrity.json` 记录逐文件清单、CRC 与路径检查；`assembly.log` 记录两包组合；`source_continuity.json` 记录数值函数 AST、校验脚本字节及历史映射源码的核对。本证据包不重复包含原大型源码/实验包。
