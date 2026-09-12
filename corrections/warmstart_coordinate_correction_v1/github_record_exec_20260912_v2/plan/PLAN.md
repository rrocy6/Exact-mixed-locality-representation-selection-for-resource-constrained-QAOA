# URSS warm-start 修正范围与实验计划 v1

计划 ID：`warmstart_coordinate_correction_plan_v1`。本文件固定实验设计和验收规则，与 `EXPERIMENT_PLAN.json`、`EXPECTED_RUNS.csv` 同时使用。

**当前状态：实验设计已固定；执行版本绑定待完成。** 本包没有执行量子实验，也没有产生修正后的性能结论。已知用户报告本机166项测试通过、MIXER NULL CONTROL PASS，证据目录为 `evidence/mixer_null_20260912T041430089422Z`；本次未取得该证据内容及修正代码的精确 hash，因此不能把它标记为本次独立验证通过。

## 1. 固定目标与修改边界

目标：在相同优化器坐标、相同经典问题与预算下，重新评估原始 E4 及 targeted addendum 的 warm-start 比较。

| 本轮包括 | 固定规则 |
|---|---|
| Mixer 参数坐标 | 保留 cold 的 exp(-i beta X) 约定；当 warm 物理公式为 exp(+i beta A) 时，在所有目标函数调用中使用 physical_beta=-optimizer_beta，并以实际修复代码测试为准 |
| Null-control | 全部 qubit 概率等于0.5时，同一参数下 cold/warm 逐点等价 |
| Targeted study | 保留原20个实例、selected designs、moments，重新运行全部480个任务 |
| Original E4 | 保留原14个实例和全部4,320个任务；2,631个正深度 warm 任务重新优化，其余1,689个先验证复用 |
| 汇总与论文 | 实例级 Student-t 汇总；更新受影响 warm-start 表、图、文字和来源说明 |

本轮不改 beam/Pareto/pruning、penalty margin、kappa、E5 标签、LP tie-break、筛选规则或实例集合；不重新运行 E1/E2/E3/E5/E6、certification 或 topology 实验。这些事项仍保留在后续工作清单中，并非被判定为无问题。

如果这些模块的改动导致表示、概率或预算改变，需单独定义修正版本并追踪下游影响，不能混入此次 mixer 单因素比较。

## 2. 基线与来源

基线为 `four-part-addendum-v1` 的已获取快照 `1cd4036a85abb93ebf8fe32a0db2dd4078627342`。它是旧结果来源，不是本机修复代码的 commit。

| 来源 | 配置 SHA-256 | 原始运行代码 commit |
|---|---|---|
| E4 v2 | `9d124ad72c0fe2b841fbfc927ec45c35cb413a6a0e01baada17f1025709d315c` | `749d39f68d29d796da0060f6c180c3306254979e` |
| Targeted addendum | `dcae3585519be308040729bc8a4548c06f46493af50e454b389165349380c632` | `5bdec984a409335ca07aa5bec867f3c5fee9cf14` |

原始 E4 路径必须是 `fibre_e1_e6_v2/results/e4_warmstart_runs.csv`，不要误用根目录下旧的 `results/e4_warmstart_runs.csv`。Targeted 路径是 `four_part_addendum_v1/strong_bias/strong_bias_warmstart_runs.csv`。

`SOURCE_INPUT_MANIFEST.csv` 固定82个输入文件的实际字节 SHA-256，含原始运行记录、配置、实例、selected list、LP diagnostics、预算、v2 designs、环境记录。它验证的是输入版本，不证明历史算法正确。

E1的124,672次原变量评估和585,408次联合评估已能从v2数据复算，不因本轮 mixer 修正重跑。Addendum分支已修复已检查的margin传递路径，不能把旧main分支的发现自动作为新增敏感性实验的重跑理由。

## 3. 固定实验组合

| 项目 | A：Targeted | B：Original E4 |
|---|---|---|
| 实例 | 原20个，每family 10个 | 原14个，每family 7个 |
| 表示 | 原selected设计 | native、full、selected及原5次matched-random draws |
| 预算 | p=1、2 | p=1、2；B=128、256，实际p按原budget plan |
| 政策 | cold、original-only、pair、independence | 保留原CSV的合法政策；没有aux的设计不凭空增加pair/independence行 |
| 重启 | 每设置3次 | 每设置3次 |
| 最终完整记录 | 480行 | 4,320行 |
| p=0 | 不允许，原计划为0行 | 原计划468行，标记为初态/预算不足记录 |

A中cold共120行、三类warm共360行，全部重跑。B中cold共1,344行（1,221个正深度、123个p=0），warm p=0共345行，warm正深度共2,631行。

`EXPECTED_RUNS.csv` 明确列出4,800个任务及其唯一task_id；task_id由study、instance、representation、random_rep_seed、design_id、budget、policy、closure、restart构成。每个任务还固定p、初始参数hash、三类seeds、moment hash及源CSV行号。重复draw若恰好产生相同design，仍保留独立draw身份。

顺序：先A，再完成B的复用验证与必要重跑。A之后决定的是B的技术重跑量，不以A中优势是否显著决定是否完成B。如果撤去整项原始E4分析，必须形成有日期的范围变更，并披露此前已经看过的结果。

## 4. 固定参数与输入恢复

- 无噪声statevector；优化损失为原始目标的期望。Encoded energy、optimal-solution probability和auxiliary inconsistency为次要诊断。
- COBYLA：每restart 60次objective evaluation，3次restart，tolerance=0.001；保留全部restart，不挑选表现最好的重启作主要汇总。
- Optimizer seeds：2026082731、2026082732、2026082733。
- Circuit seeds：2026082741、2026082742、2026082743。
- Measurement seeds：2026082751、2026082752、2026082753。Statevector不把seed或shots当额外独立重复。
- 保留gamma初始区间[0,2pi]、beta初始区间[0,pi]、原seed派生与参数顺序；它们是初始化区间，不自动变为优化边界。
- Clipping delta=0.05；pair概率由raw pair moment裁剪一次；independence为已裁剪original概率的乘积，不再次裁剪。
- 保留原margin=1、原penalties、auxiliary顺序、表示和compiled layer budgets。
- 原E4使用原归档的first LP optimum概率；targeted使用原归档的deterministic optimum-face概率。优先从归档的raw/clipped diagnostics重建，并核对moment hash；不要重新求LP后静默使用不同最优面上的解。
- 不能重新筛选20个targeted实例。配置共安排每family 500次生成尝试，保存的567条是筛选候选（93 spin-glass、474 Max-3SAT），不是1000个全部生成成功的实例。缺少的历史失败日志不能伪造。

**执行入口要求：** 此计划不是原 `run_four_part_addendum_v1.py` 的配置替换文件。已检查的旧 `--phase strong-bias` 路径会重新生成候选池、求LP和选择设计，不适合作为本计划的直接重跑入口。执行器应直接读取冻结实例、归档概率、actions和budget。若actions需要恢复，先用原selector版本恢复并核对design_id及原参数回放，将最终编码、概率、actions和budget导出并hash，再启动新优化；无法还原则记blocker。

## 5. 开跑前绑定与验收

在新执行目录写 `EXECUTION_BINDING.json`，不可覆盖此计划。必须记录：

1. 本计划SHA-256和source input manifest SHA-256。
2. 修复代码的真实commit及source tree manifest；有未提交改动时记录diff hash并提交或单独归档，不能用旧commit冒充修复版本。
3. Python、NumPy、SciPy、Qiskit等实际版本、操作系统、依赖锁及环境snapshot hash。环境与原档不同需披露，并执行对应复用规则。
4. Null-control证据路径、文件manifest、测试覆盖、实测最大误差；166项通过是用户报告，绑定后才能认定为对应执行版本的证据。
5. 每个冻结设计的实际编码、probabilities、auxiliary映射、预算的manifest。
6. corrected结果此前是否已被查看。若已经看过，不称为前瞻预注册，记录真实时间线。

Null-control须覆盖多组参数、p=1/2、native和含aux设计、四种policy调用路径；测试时显式将全部qubit概率设0.5。仅original概率0.5时，independence aux概率可能是0.25，不能误当作完全零信息对照。

小规模float64检查：相位对齐statevector的L2差<=1e-12，概率绝对差<=1e-12，能量用atol=1e-12、rtol=1e-12；还检查范数、指标和参数映射。固定环境的优化器回归允许浮点容差，不要求跨平台逐位相同。差异需定位，不能为了让测试通过而事后随意放宽容差。

## 6. 重跑、复用与失败规则

A全部480行重新优化，旧cold行用于前后技术对照。B的2,631个正深度warm行必须重新优化，不能把旧最优参数的beta翻转或旧结果重新评分就标为修正实验。

B其余1,689行仅是复用候选。每行必须用新执行器回放保存的参数/初态，核对原目标、encoded energy、成功概率、inconsistency和范数；同时验证原输入、cold代码路径、初始化、optimizer和数值环境等价。指标参考容差：概率/范数atol=1e-10；能量atol=1e-10、rtol=1e-10。

当cold路径、optimizer、初始化及固定数值环境均已证明未变时，不要求重做所有cold优化。若相关依赖等价无法确认，则对受影响分组的全部正深度cold任务统一重跑，避免按目标值选择复用。p=0只需重评估初态；如沿原schema保留“60 evaluations”，必须说明其为重复初态评估/历史记账，不称为60次有效优化。

每行输出属于 `RERUN_PASS`、`REUSED_VALIDATED`、`FAILED` 或 `MISSING`。复用行保留source文件hash、source行号、原code_commit，另列validation commit；不能把复用结果伪装为由新commit重新优化。

技术性失败允许在完全相同输入和seed下重试一次，保存两次attempt，不按优劣选结果。修改环境或实现须重新绑定。若仍有失败/缺失，包标为INCOMPLETE并完整报告原因，不补造数据、不静默缩小集合。只有4,800个预期task全部交代清楚且无未解决失败/缺失，才标完整完成。

## 7. 固定统计与解释

先按同一draw/policy/budget平均3次restart，再按原5次random draws平均（如适用），最后在同一个raw instance内计算政策差；按family与budget分别汇总。无random的selected比较跳过draw平均。

主要对比为pair-minus-cold；同时完整报告original-only-minus-cold、independence-minus-cold、pair-minus-original-only、pair-minus-independence。低目标更好，负差值有利于前一政策。

Targeted每family n=10；原E4的主warm-start表保留原common selected active-aux subset（spin-glass 2、Max-3SAT 7），同时报告全计划的诊断汇总。零层与正深度比较分开标识，不能悄悄删掉零层后保留旧分母。

95%区间为实例级双侧Student-t，df=n-1；n<2记不可估计。普通描述均值和paired差值都明确分母。预定区间为未做多重比较调整的探索性结果，不据其声称普遍优势或已证明等效。

Targeted与原E4不得合并。CI包含0说明证据不明确，不说明没有任何效应；pair-vs-original-only/independence的额外收益单独讨论。即使targeted Max-3SAT改善，也仅限定于原signal-enriched subset。**优势不显著不是验收失败；对照不一致或结论超出数据才是问题。**

## 8. 交付与后续事项

每次执行使用 `corrections/warmstart_coordinate_correction_v1/<unique_execution_id>/`，保存binding、实物输入manifest、raw rows、reuse审计、failed attempts、逐实例paired rows、summary、表图、环境、RUN_COMMANDS、CORRECTION_AUDIT和SHA256 manifest。保留旧E4与addendum的所有字节。

正式manifest应排除自身和明示的临时日志，再由外部sidecar记录manifest hash，避免递归自哈希。Audit状态、误差和行数从实际检查生成，不预填PASS或0。

本轮完成后再更新Overleaf的warm-start表、性能图、方法中的beta约定、Results/Discussion/Conclusion和provenance。按LaTeX label定位，不依赖旧PDF的Table 16/17编号。LP信号图只有输入确实变化才更换。当前计划和代码保存在项目资料/GitHub，不能把本计划当作论文图或结果上传Overleaf替换。

后续独立处理：kappa非恒等项定义和派生表；beam前缀保留及对已选design的影响；按实际运行版本复核margin sensitivity；E3/E6汇总复现；E5量纲和标签；整篇论文残留与最终编译。这些事项需要各自证据，不因本轮结束自动PASS。

任何范围变化用新编号amendment，记录理由、时间和已查看结果的范围；不要改写此冻结文件。
