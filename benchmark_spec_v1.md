# URSS Benchmark Specification v1.0

**Project:** Exact Selective Locality Reduction for Warm-Started QAOA  
**Document owner:** Benchmark / Applications负责人（Yiding）  
**Implementation partner:** Code / Numerical Pipeline负责人  
**Status:** v1.0 draft for joint review and project-lead approval  
**Method reference:** `URSSNEWEST.pdf`, 2026-08-13  
**Scope:** Max-3SAT与cubic spin-glass benchmark的定义、生成、验证、分层、划分和审计

---

## 1. Purpose

本benchmark不是为了挑选几个“看起来效果好”的例子，而是建立一个固定、可复现的实验坐标系，用来回答：

> 在什么样的problem structure和hardware connectivity下，selective quadratization相对于all-native和fully quadratized表示有帮助、影响很小或有害？

当前主研究轴只有三个：

1. **Sparsity：** canonical cubic interactions有多稀疏；
2. **Auxiliary reuse：** 不同cubic terms有多少pair可以共享；
3. **Connectivity：** 编译目标的连接限制带来多少routing压力。

Coefficient sign balance、coefficient heterogeneity和大规模scaling仍然记录为diagnostics，但不构成当前主实验网格。

本specification只规定原始问题和数据。Representation selection、compiler、QAOA、optimizer和noise的参数由独立的实验配置规定，不能反向改变benchmark。

---

## 2. Non-negotiable principles

以下规则从v1开始固定：

1. 所有原始实例必须能由versioned config和固定seed重现。
2. 所有representation必须来自同一个原始`instance_id`。
3. 同一原始实例的native、selective、full和random encodings必须属于同一个split。
4. Train/validation/test在正式结果产生前冻结。
5. Test instances不能用于调整selector weights、beam width、risk tolerances、compiler seed、QAOA optimizer或noise设置。
6. 共同质量指标必须使用原始目标`f(x)`，不能用不同encoding自己的`F_sigma(x,y)`直接比较。
7. Coefficient aggregation必须先于cubic support、pair shadow、penalty和feature计算。
8. 聚合后系数严格为0的monomial删除；不能用未经声明的数值tolerance删除小系数。
9. 不得根据preliminary winner、图形是否好看或QAOA表现重新挑选test instances。
10. 任何定义、分布、normalisation、排除规则或split变化都必须升spec/config版本并生成新IDs。

---

## 3. Common notation and canonical representation

### 3.1 Boolean variables

所有进入实验管线的canonical objective使用：

```text
x_i in {0,1}, i = 1,...,n
```

Canonical pseudo-Boolean objective写为：

```text
f(x) = sum_A c_A * product_{i in A} x_i
```

其中：

- support `A`使用严格递增的变量编号；
- constant使用空support `()`；
- 同一support的coefficients必须相加；
- Boolean multilinear规则为`x_i*x_i=x_i`；
- 聚合后`c_A=0`的项删除。

### 3.2 Canonical cubic support

Canonical cubic support定义为：

```text
C3(f) = {A : |A|=3 and c_A != 0}
```

定义：

```text
m3 = |C3(f)|
```

必须在所有clauses/hyperedges展开并聚合以后计算，不能直接把原始三变量clauses或hyperedges数量当作`m3`。

### 3.3 Pair shadow and pair degree

Pair shadow为所有canonical cubic supports中出现过的二变量pair：

```text
pair_shadow = union over A in C3(f) of all two-element subsets of A
```

对每个pair `p`：

```text
d(p) = number of canonical cubic supports containing p
Delta2 = max_p d(p)
```

### 3.4 Primary sparsity measure

主要sparsity coordinate使用canonical cubic density：

```text
cubic_density = m3 / choose(n,3)
```

同时记录：

```text
cubics_per_variable = m3 / n
```

主分析使用连续值，不只保留`sparse/intermediate/dense`标签。标签仅用于coverage summaries。

### 3.5 Primary reuse measure

主要reuse coordinate使用pair-shadow compression：

```text
pair_reuse_score = 1 - |pair_shadow| / (3*m3),  if m3 > 0
```

解释：若所有cubic terms的三个pairs都互不重复，score为0；共享pairs越多，score越高。

同时记录：

- `Delta2`；
- `d(p)` histogram；
- fraction of pairs with `d(p)>=2`；
- fraction of cubic terms that share at least one pair；
- exact pair-cover number `tau2`（仅oracle tier或可求解实例）；
- `tau2`的bound/status（较大实例）。

Reuse labels由生成后的实际`pair_reuse_score`确定，不由generator请求的标签直接决定。V1 coverage bins固定为：

```text
low reuse:          0.00 <= pair_reuse_score < 0.10
intermediate reuse: 0.10 <= pair_reuse_score < 0.25
high reuse:         0.25 <= pair_reuse_score
```

主统计仍使用连续score；bins只用于数据覆盖、分层抽样和简洁展示。若pilot证明某family的某个bin在合法实例中不可达到，必须报告coverage hole并通过新版本修改，不能后验移动阈值。

### 3.6 Connectivity is not part of the raw instance

Raw mathematical instance不包含特定硬件。Connectivity通过独立的`topology_profile_id`加入compile/run记录。

每个需要compiled-resource比较的原始实例至少使用：

1. `reference_all_to_all`：论文Appendix D.1的reference architecture；
2. `device_sparse_v1`：一个固定、真实设备拓扑派生的coupling map，完整adjacency、basis gates和direction存入compiler config。

所有representations必须使用相同topology profiles和相同compiler seed bundle。

---

## 4. Benchmark family A: Weighted Max-3SAT

### 4.1 Mathematical definition

一个实例包含`n`个Boolean variables和`m_clause`个weighted three-literal clauses：

```text
C = (literal_i OR literal_j OR literal_k), weight w_C > 0
```

Literal的false indicator为：

```text
positive literal x_i:     u(x_i) = 1-x_i
negative literal not x_i: u(not x_i) = x_i
```

Clause violation polynomial：

```text
P_C(x) = u(literal_i) * u(literal_j) * u(literal_k)
```

原始目标为最小化被违反clauses的总权重：

```text
f_3SAT(x) = sum_C w_C * P_C(x)
```

### 4.2 Primary weighting rule

主benchmark使用small positive integer weights：

```text
w_C sampled uniformly from {1,2,3,4,5}
```

理由：

- 与最新版论文中的weighted Max-3SAT定义一致；
- 产生可手算、可精确保存的integer coefficients；
- 允许mixed coefficient masses和penalty scale出现差异；
- 不引入floating-point zero判断。

Unweighted实例`w_C=1`仅用于unit tests或明确标记的diagnostic，不作为独立主实验轴。

### 4.3 Clause construction rules

每条clause：

1. 必须包含三个不同变量；
2. 每个literal sign独立以概率`1/2`选择positive或negative；
3. 不允许相同的signed-literal triple重复，不论抽到的weight是否不同；
4. 允许同一变量triple出现不同sign patterns；
5. 因变量不重复，不会出现同一clause内部的`x_i OR not x_i` tautology；
6. generator必须保证每个变量至少在一个clause中出现；否则重新生成并记录rejection。

“相同clause”由排序后的signed literals判断。Weight是该唯一clause的属性，不允许用不同weight重复加入同一signed clause。另记录signed-clause hash以审计重复。

### 4.4 Clause density

记录：

```text
clause_density = m_clause / n
```

V1目标levels为：

```text
low:          approximately 2
intermediate: approximately 4
high:         approximately 6
```

实际`m_clause`取最接近`target*n`的整数，并受合法不同clauses数量限制。

这些levels只控制raw sampling effort。正式regime analysis仍使用aggregation后的`cubic_density`和`pair_reuse_score`。

### 4.5 Reuse control

Max-3SAT generator支持两种triple proposal方式，但最终由实际feature决定所在reuse bin：

#### Uniform proposal

从全部不同的三变量sets中均匀抽取，用作低reuse baseline的主要来源。

#### Anchor-pair proposal

1. 先从变量中选择若干anchor pairs；
2. 对某个anchor pair采样不同的第三变量形成clauses；
3. sign和weight仍按固定规则独立采样；
4. anchor数量和每个anchor的使用次数写入generator config。

Anchor-pair proposal只改变结构重叠，不改变literal-sign或weight分布。

Generator可使用rejection/oversampling使candidate pool覆盖低、中、高实际reuse，但不能在查看selector/QAOA结果后补挑test instances。

### 4.6 Direct evaluator

必须有独立的clause evaluator：

1. 直接判断每个literal真/假；
2. 判断clause是否被违反；
3. 累加被违反clause的weight。

Direct evaluator不得调用PUBO evaluator。它是canonical transformation的独立校验来源。

### 4.7 Required raw fields

每个Max-3SAT实例至少保存：

```text
family = "max3sat"
n
m_clause
clauses: signed literal triples
weights
clause_density
generator_mode
generator_parameters
master_seed
instance_seed
spec_version
generator_version
```

---

## 5. Benchmark family B: Cubic spin glass

### 5.1 Original variable convention

原始spin变量固定为：

```text
s_i in {-1,+1}
```

主benchmark objective为pure cubic spin glass：

```text
E(s) = sum_{i<j<k} K_ijk * s_i*s_j*s_k
```

V1主benchmark固定：

```text
c = 0
h_i = 0
J_ij = 0
```

理由：当前主问题是cubic structure、reuse与connectivity；加入独立linear/quadratic random terms会增加额外实验轴。Generator可以支持lower-order terms，但非零lower-order版本不进入V1主结果，除非升版本或明确标记为diagnostic。

### 5.2 Cubic coefficient distribution

每个active hyperedge的coefficient固定从Rademacher distribution采样：

```text
K_ijk in {-1,+1}, each with probability 1/2
```

Sign distribution固定，不把sign balance作为主实验轴。仍保存实际positive/negative counts和masses作为diagnostic。

不允许同一个unordered hyperedge重复；hyperedge必须满足`i<j<k`。

### 5.3 Boolean conversion

唯一转换约定：

```text
s_i = 1 - 2*x_i
```

因此：

```text
s_i*s_j*s_k
= 1
  - 2*(x_i+x_j+x_k)
  + 4*(x_i*x_j+x_i*x_k+x_j*x_k)
  - 8*x_i*x_j*x_k
```

所有hyperedges转换后必须进行canonical coefficient aggregation。

V1 raw mathematical objective不做instance-dependent normalisation。若circuit/QAOA阶段需要整体正比例rescaling，必须：

1. 对同一instance的所有representations使用同一个scale；
2. 保存`objective_scale`和`objective_offset`；
3. ground truth与共同评分恢复到原始`E(s)`或等价原始`f(x)`单位。

### 5.4 Hyperedge density

记录：

```text
hyperedge_density = m_edge / choose(n,3)
cubics_per_variable_raw = m_edge / n
```

V1生成目标采用每变量hyperedge负载：

```text
low:          m_edge approximately 1*n
intermediate: m_edge approximately 2*n
high:         m_edge approximately 4*n
```

若目标超过`choose(n,3)`则截断到合法最大值并记录。正式分析使用Boolean转换和aggregation后的canonical features。

### 5.5 Reuse control

Spin-glass generator使用与Max-3SAT对应的两类proposal：

#### Uniform hyperedges

从所有三变量hyperedges中均匀、无重复采样。

#### Anchor-pair hyperedges

先采样anchor pairs，再为每个pair采样多个不同第三变量。Coefficient signs继续按固定`1/2`规则采样。

最终reuse level只根据canonical `pair_reuse_score`确定。Generator mode和requested reuse仅作为provenance保存。

### 5.6 Direct evaluator

必须有独立Ising evaluator：

```text
E_direct(s) = sum K_ijk*s_i*s_j*s_k
```

小实例对全部assignments验证：

```text
E_direct(s(x)) == f_boolean(x)
```

大实例使用固定数量的随机assignments交叉验证，数量写入validation config。

### 5.7 Required raw fields

```text
family = "cubic_spin_glass"
n
m_edge
hyperedges
K_coefficients
c = 0
h = all zero
J = all zero
hyperedge_density
generator_mode
generator_parameters
master_seed
instance_seed
spec_version
generator_version
ising_to_boolean_convention = "s=1-2x"
```

---

## 6. Common derived metadata

每个instance对应一行metadata。至少包含：

### 6.1 Identity and provenance

```text
instance_id
family
spec_version
generator_version
config_hash
master_seed
instance_seed
created_at
raw_file
raw_hash
split
tier
```

### 6.2 Size and canonical structure

```text
n
raw_term_count
canonical_term_count
canonical_degree
m3
cubic_density
cubics_per_variable
pair_shadow_size
pair_reuse_score
Delta2
pair_degree_mean
pair_degree_max
fraction_reused_pairs
fraction_cubics_with_shared_pair
tau2
tau2_status
tau2_lower_bound
tau2_upper_bound
overlap_graph_nodes
overlap_graph_edges
overlap_graph_components
overlap_graph_max_degree
```

### 6.3 Coefficients and penalties

```text
coefficient_min
coefficient_max
coefficient_abs_max
coefficient_l1
positive_cubic_mass
negative_cubic_mass
positive_cubic_count
negative_cubic_count
canonical_cancellation_count
canonical_cancellation_mass
candidate_pair_count
```

Exact penalty profile依赖representation assignment，因此不作为raw instance field。Instance metadata只保存计算penalty所需的canonical coefficients；design tables保存每个design的`T_p`、`M_p`、`M_max`。

### 6.4 Ground truth fields

```text
optimum_original
number_of_optima
first_excited_value
first_excited_gap
near_optimal_count_optional
solver
solver_version
solver_status
optimality_certificate_or_gap
ground_truth_runtime
verification_method
```

不能计算的字段使用明确的missing code，例如`not_attempted`、`timeout`或`unknown`，不能混用空字符串和0。

---

## 7. Dataset tiers

一个原始instance只生成一次，但可被一个或多个实验阶段引用。`tier`表示其主要用途。

### 7.1 Oracle tier

用途：

- exhaustive pointwise exactness；
- penalty sharpness；
- complete/safely certified design comparison；
- selector hit rate和regret；
- exact ground truth。

V1目标约束：

```text
n in {5,6,7,8}
m3 <= 8 after canonical aggregation
```

若`4^m3`完整设计枚举超出实际budget，可使用论文certification interface，但必须报告status和bounds。

目标样本数：

```text
30 Max-3SAT instances
30 spin-glass instances
```

每个family尽量覆盖3个sparsity bins × 3个reuse bins；不足的cell记录coverage limitation，不根据实验winner补样本。

### 7.2 QAOA tier

用途：

- noiseless budget-matched QAOA；
- warm-start ablations；
- pair-moment vs independence ablation；
- limited noise subset。

V1候选原始规模：

```text
n in {6,8,10}
```

共同width feasibility规则：进入四representation主比较的instance，所有被比较representations都必须满足同一个`Qmax`。`Qmax`由frozen experimental protocol规定，不能对不同representations使用不同上限。

目标样本数：

```text
36 Max-3SAT instances
36 spin-glass instances
```

目标是每个family在3个sparsity bins × 3个reuse bins中约有4个实例。若某些组合在合法生成和width约束下不可达到，应报告而不是用后验选择填满。

### 7.3 Compilation tier

用途：

- logical resources；
- reference all-to-all compiler；
- device topology routing sensitivity；
- selector compilation cost。

V1候选规模：

```text
n in {8,12,16,20}
```

目标样本数：

```text
90 Max-3SAT instances
90 spin-glass instances
```

当前论文不进行大规模scaling主研究；`n=20`只用于资源趋势和routing，不支持一般scalability结论。

### 7.4 Limited noise subset

Noise subset必须在看到noise winner前确定。

V1目标：

```text
9 Max-3SAT instances
9 spin-glass instances
```

每个family从QAOA test candidate中按预先定义的sparsity/reuse cells选取，不按noiseless表现或selective winner挑选。Noise levels和topology由实验协议冻结。

### 7.5 Pilot and resource adjustment rule

上述样本数和规模是V1目标。正式冻结前必须运行不使用test结果的timing/memory pilot。

若资源不允许：

1. 优先减少每cell样本数，不改变数学定义；
2. 保持两个families和主轴覆盖；
3. 记录调整理由；
4. 发布`benchmark_spec_v1.1`或新的dataset config version；
5. 不得静默修改本文件中的目标后继续称为相同V1数据集。

---

## 8. Train, validation and test splits

### 8.1 Split ratio

每个family和tier分别按：

```text
train      60%
validation 20%
test       20%
```

若cell样本太少，优先保证test至少有一个实例，并在manifest中记录不平衡。

### 8.2 Assignment procedure

1. 先生成并验证raw candidate pool；
2. 计算`instance_id`和canonical features；
3. 在任何selector/QAOA结果产生前，根据固定split seed和`instance_id`分配split；
4. 在每个family/tier内检查sparsity/reuse coverage；
5. 冻结manifest和hash。

不得人工把“有趣”或“困难”的实例移动到test。若coverage严重不足，必须生成新的candidate pool并发布新manifest版本；旧manifest保留。

### 8.3 Related data rule

- 同一raw instance的所有encodings共享split；
- 同一raw instance的不同topology compilation共享split；
- 同一raw instance的所有optimizer/noise seeds共享split；
- derived files不能拥有独立split；
- exact duplicate raw instances必须去重；
- generator family中的手工worked example只属于`unit/golden`，不进入train/validation/test统计。

### 8.4 Allowed use

```text
train:
  selector weights, risk thresholds, beam width,
  compiler/optimizer defaults, analysis code development

validation:
  choose among predeclared candidate settings,
  confirm final frozen protocol

test:
  one final locked evaluation and reported uncertainty
```

---

## 9. Exclusion and failure rules

### 9.1 Exclude before canonical evaluation

排除并重新生成：

- clause含重复变量；
- exact duplicate clause违反spec；
- invalid hyperedge或duplicate hyperedge；
- 变量完全未出现；
- 文件/schema损坏；
- seed/config/provenance缺失。

### 9.2 Exclude after canonicalisation

从当前cubic benchmark排除但必须保留audit record：

- `m3=0`；
- canonical degree小于3；
- direct-vs-canonical validation失败；
- Ising-vs-Boolean validation失败；
- instance hash与已有实例重复。

Canonical cancellation本身不是排除理由。只要`m3>0`，保留并记录cancellation。

### 9.3 Tier-specific non-eligibility

以下不删除raw instance，只标记不适合某tier：

- 无法在规定时间内获得ground truth：不进入需要exact truth的oracle/QAOA主评分；
- 某个被比较representation超过共同`Qmax`：不进入四representation QAOA主比较，但可保留在compilation tier；
- compiler timeout/failure：保留failure status，不把它静默移除；
- exact `tau2` timeout：保存bounds/status，仍可用于不要求exact `tau2`的实验。

### 9.4 Forbidden exclusions

严禁因为以下原因删除test instance：

- selective没有获胜；
- 结果接近0或不显著；
- 图形不好看；
- optimizer表现不稳定；
- routing结果与假设不符；
- instance太容易或太难，但该难度未被预先排除规则覆盖。

这些都属于应报告的结果或limitation。

---

## 10. Validation protocol

### 10.1 Unit and golden tests

必须包含：

- Section 6.1.1五变量Max-3SAT worked example；
- Max-3SAT全部8种literal-sign patterns；
- Rosenberg penalty全部8个`(a,b,y)` assignments；
- mixed-sign shared-pair threshold；
- isolated-pair threshold；
- 至少3个手工spin-glass转换实例。

### 10.2 Exhaustive validation

对所有oracle-tier和可承受的QAOA-tier实例：

```text
for all x:
  direct evaluator == canonical PUBO evaluator
```

Spin glass验证：

```text
for all x:
  E_direct(s=1-2x) == f_boolean(x)
```

### 10.3 Large-instance spot validation

不能穷举时，对每个instance使用独立validation seed抽取固定数量assignments。V1默认目标：

```text
1024 random assignments per instance
```

若变量规模使distinct assignments少于1024，则使用全部assignments。任何mismatch都使instance validation失败，并停止该generator version的正式生成。

### 10.4 Reproducibility validation

固定seed重跑必须得到完全相同的：

- raw clauses/hyperedges；
- weights/coefficients；
- canonical coefficient dictionary；
- metadata；
- instance ID和file hash。

不同机器上的timestamps可以不同，但不能进入content-derived ID。

---

## 11. Ground truth protocol

### 11.1 Preferred order

1. 小实例：穷举全部`x`；
2. 较大Max-3SAT：独立weighted-clause solver或MILP/CP-SAT；
3. 较大spin glass：MILP/CP-SAT或其他可验证exact solver；
4. 无法证明最优时记录best bound、gap和status，不伪装成ground truth。

### 11.2 Required outputs

- original optimum；
- 至少一个original minimiser；
- number of optima（可精确计算时）；
- first excited value/gap（可计算时）；
- solver status和runtime；
- certificate或optimality gap；
- 第二种方法的抽样复核结果。

### 11.3 Common scoring

所有QAOA sample在丢弃auxiliary bits后，使用原始direct evaluator评分：

- Max-3SAT：被违反clauses的总权重；
- spin glass：原始`E(s)`。

Encoded energy和auxiliary inconsistency可以另报，但不能替代共同主评分。

---

## 12. Benchmark audit before formal experiments

正式实验前生成`benchmark_audit_v1`，至少包含：

1. 每个family/tier/split的数量；
2. 所有排除和non-eligibility数量及原因；
3. `n`、`m3`、cubic density和`m3/n`分布；
4. pair-reuse score、`Delta2`和pair-degree分布；
5. sparsity × reuse二维coverage；
6. canonical cancellation分布；
7. coefficient range和positive/negative masses；
8. ground-truth optimum、degeneracy和gap分布；
9. duplicate/hash检查；
10. train/validation/test leakage检查；
11. QAOA共同width feasibility；
12. 已知coverage holes和原因。

Audit只能用于检查数据质量和预先定义的coverage，不能使用representation winner或QAOA performance决定保留/排除。

---

## 13. File and ID contract

### 13.1 Recommended layout

```text
data/
  raw/
    max3sat/
    cubic_spin_glass/
  canonical/
  metadata/
  ground_truth/
  manifests/
  audit/
```

### 13.2 Instance ID

`instance_id`必须由以下canonical serialized content的hash得到：

```text
family
raw mathematical instance
variable convention
generator/spec version
normalisation convention
```

不得包含：

- representation choice；
- compiler/topology；
- selector parameters；
- QAOA/optimizer/noise parameters；
- split name；
- timestamp；
-实验结果。

### 13.3 Ownership

你负责确认：

- 数学定义；
- generator distributions；
- feature meanings；
- exclusion rules；
- coverage和split用途。

她负责实现：

- schema/serialization；
- deterministic IDs；
- canonicalisation；
- validators；
- metadata extraction；
- manifests和audit tables。

任何字段含义变化必须双方确认。

---

## 14. Deliverables

### Benchmark负责人交付

```text
benchmark_spec_v1.md
feature_dictionary_v1.md
max3sat_direct_evaluator specification/tests
spin_glass_direct_evaluator specification/tests
manual pilot examples
benchmark_audit interpretation
Sections 6 and 7 benchmark text
```

### Code负责人交付

```text
instance_schema_v1
generator implementations
canonical PUBO core
validators and deterministic IDs
metadata extraction
ground-truth runners
manifests and audit tables
one-command pilot generation/validation
```

### Joint sign-off package

```text
approved benchmark_spec version
approved schema version
golden-test report
pilot validation report
timing/resource report
frozen manifests and hashes
benchmark audit report
open limitations
```

---

## 15. Decisions requiring explicit joint or project-lead approval

V1 proposes concrete defaults above, but the following must be acknowledged before the document becomes `frozen`：

| Decision | V1 proposal | Required approval |
|---|---|---|
| Max-3SAT weighting | Uniform integer weights `{1,...,5}` | Benchmark + project lead |
| Max-3SAT raw density targets | `m/n approximately 2,4,6` | Benchmark + pilot review |
| Spin-glass lower-order terms | Main benchmark sets `h=J=0` | Benchmark + project lead |
| Spin coefficients | `K in {-1,+1}` equally likely | Benchmark + project lead |
| Spin hyperedge loads | `m approximately n,2n,4n` | Benchmark + pilot review |
| Main structure axes | sparsity, reuse, connectivity only | Already aligned with professor; record sign-off |
| Dataset target counts | 30/36/90 per family for oracle/QAOA/compilation | Joint resource pilot |
| QAOA common width `Qmax` | Defined later in experimental protocol | Code + project lead |
| Device topology | Fixed `device_sparse_v1` adjacency in compiler config | Code + project lead |
| Noise subset | 9 per family, selected structurally before noise results | Joint approval |

若其中任何选择被修改，更新本文件版本和changelog；不能只在代码中改变。

---

## 16. Acceptance checklist for freezing v1

- [ ] 项目负责人确认两个benchmark families和主轴；
- [ ] 合作人确认所有字段和generator规则可实现；
- [ ] 五变量golden test通过；
- [ ] 8种Max-3SAT sign patterns通过；
- [ ] 3个spin-glass手工转换通过；
- [ ] schema round-trip和deterministic ID通过；
- [ ] fixed-seed重跑完全一致；
- [ ] pilot显示目标sparsity/reuse coverage可达到；
- [ ] timing pilot支持或已通过新版本调整目标样本数；
- [ ] exclusion/audit逻辑已实现；
- [ ] train/validation/test manifest在正式结果前冻结；
- [ ] 本文件状态由`draft for review`改为`frozen`并记录日期/hash。

---

## 17. Changelog

### v1.0 draft

- 定义weighted Max-3SAT主benchmark；
- 定义pure cubic spin-glass主benchmark；
- 固定`x in {0,1}`和`s=1-2x`转换；
- 将sparsity、pair reuse、connectivity设为主实验轴；
- 定义canonical features、dataset tiers、splits、exclusions和audit；
- 给出V1目标规模和需审批的资源相关选择；
- sign balance与large-scale scaling降为diagnostics/future work。
