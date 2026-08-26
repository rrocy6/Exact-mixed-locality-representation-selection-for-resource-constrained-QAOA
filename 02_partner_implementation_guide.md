# 给代码负责人的逐步实现说明

目标：把 Section 7.1.1 的五变量 Max-3SAT 例子做成一个自动化 golden regression test。此阶段不生成随机实例、不运行 QAOA、不比较性能。

## Step 0：确认本轮范围

本轮只实现并测试以下数据流：

```text
weighted clauses
    -> direct clause evaluator
    -> expanded/canonical PUBO
    -> selective/full encodings
    -> exhaustive pointwise exactness checks
```

本轮不要做：

- 随机 Max-3SAT generator；
- cubic spin-glass generator；
- selector、compiler、QAOA 或 noise；
- 最终 benchmark schema；
- 任何“哪个 encoding 更好”的性能结论。

## Step 1：建立可由终端运行的测试入口

建议结构：

```text
src/
  pbo.py
  penalties.py
  encodings.py
  exactness.py
tests/
  test_max3sat_worked_example.py
```

如果仓库已经有等价结构，可以使用现有结构。要求是：

- 测试通过一个明确命令运行，例如 `python -m pytest -q`；
- 不依赖 Jupyter notebook 中已执行过的 cell；
- 失败时报告具体 assignment、expected value 和 actual value。

完成本 step 的可见结果：测试文件能被测试框架发现，即使其中暂时只有占位测试。

## Step 2：编码原始 clauses

建议用带符号整数表示 literal：

```text
+i means xi
-i means not xi
```

本例可表达为：

```python
clauses = [
    {"literals": (-1, -2, -3), "weight": 5},
    {"literals": ( 2,  3,  4), "weight": 4},
    {"literals": (-1, -4, -5), "weight": 2},
]
```

实现 literal truth evaluator：

```text
if literal is +i: truth = x_i
if literal is -i: truth = 1-x_i
```

实现 direct clause evaluator：

```text
clause is violated if all three literal truth values are 0
objective = sum of weights of violated clauses
```

注意不要在 direct evaluator 中调用 polynomial evaluator，否则“双重验证”会共享同一个 bug。

至少添加三个容易人工核对的测试：

```text
x=(0,0,0,0,0) -> only C2 is violated -> f(x)=4
x=(1,1,1,0,0) -> only C1 is violated -> f(x)=5
x=(1,1,1,1,1) -> C1 and C3 are violated -> f(x)=7
```

完成本 step 的可见结果：上述三个断言通过。

## Step 3：实现 clause 到 polynomial 的转换

对每个 literal 建立 false-indicator polynomial：

```text
positive literal +i: 1-x_i -> {(): 1, (i,): -1}
negative literal -i: x_i   -> {(i,): 1}
```

一个 clause 的 violation polynomial 是三个 false-indicator polynomials 的乘积，再乘 clause weight。

实现 polynomial multiplication 时遵守 Boolean multilinear 规则：

```text
x_i*x_i = x_i
support multiplication = set union
support is stored as a sorted immutable tuple
coefficients with the same support are added
zero coefficients are removed after aggregation
```

例如：

```text
(2,3) * (3,4) -> (2,3,4)
```

而不是保存重复的 `(2,3,3,4)`。

完成本 step 的可见结果：三个 clause 分别得到：

```text
C1 -> {(1,2,3): 5}

C2 -> {
  (): 4,
  (2,): -4, (3,): -4, (4,): -4,
  (2,3): 4, (2,4): 4, (3,4): 4,
  (2,3,4): -4
}

C3 -> {(1,4,5): 2}
```

## Step 4：实现 canonicalization 和 PUBO evaluator

Canonicalization 至少必须做到：

1. support 排序；
2. support 中重复变量去重；
3. 相同 support 系数聚合；
4. 聚合后为零的 coefficient 删除；
5. 输出顺序不依赖 dictionary insertion order；
6. 再次 canonicalize 结果不变，即幂等。

PUBO evaluator：

```text
value = sum over supports A of c_A * product(x_i for i in A)
empty support contributes its constant coefficient
```

在测试中直接断言完整 coefficient dictionary 等于手算表：

```python
expected = {
    (): 4,
    (2,): -4,
    (3,): -4,
    (4,): -4,
    (2,3): 4,
    (2,4): 4,
    (3,4): 4,
    (1,2,3): 5,
    (2,3,4): -4,
    (1,4,5): 2,
}
assert canonical_coefficients == expected
```

不要只测试两个 polynomial 在少数点上的值相同，因为 coefficient aggregation 本身也是本项目要验证的输出。

完成本 step 的可见结果：完整 coefficient 字典逐项匹配，degree 为 3，非零 terms 数为 10。

## Step 5：完成 direct-vs-canonical 的 32 点交叉验证

枚举全部五变量赋值：

```python
from itertools import product

for bits in product((0, 1), repeat=5):
    direct_value = evaluate_weighted_clauses(clauses, bits)
    pubo_value = evaluate_pubo(coefficients, bits)
    assert pubo_value == direct_value, {
        "x": bits,
        "direct": direct_value,
        "pubo": pubo_value,
    }
```

注意变量编号转换：数学中为 `x1,...,x5`，Python tuple 中通常是 `bits[0],...,bits[4]`。这一处很容易产生 off-by-one bug。

完成本 step 的可见结果：

```text
assignments checked = 32
direct-vs-canonical mismatches = 0
```

## Step 6：提取 cubic support、pair shadow 和 reuse

从 canonical PUBO 中重新提取所有长度为 3 的 supports，不能从原始 clauses 直接假设它们仍存在，因为不同 clauses 展开后可能发生 coefficient cancellation。

期望：

```text
C3(f) = {(1,2,3), (2,3,4), (1,4,5)}
pair-shadow size = 8
d(2,3) = 2
all other pair degrees = 1
Delta_2 = 2
tau_2 = 2
```

`tau_2` 在本例可用 exhaustive pair-cover 检查；如果本轮尚未实现通用 pair-cover solver，至少把本例作为显式 golden assertion 保存。

完成本 step 的可见结果：上述结构量全部匹配手算表。

## Step 7：实现并测试 Rosenberg penalty

实现：

```python
def rosenberg(a, b, y):
    return a*b - 2*a*y - 2*b*y + 3*y
```

枚举 `a,b,y` 的 8 种情况，断言：

```text
P_R(a,b,y) >= 0
P_R(a,b,y) == 0 if and only if y == a*b
```

并逐项匹配手算表中的期望序列：

```text
(0,0,0)->0
(0,0,1)->3
(0,1,0)->0
(0,1,1)->1
(1,0,0)->0
(1,0,1)->1
(1,1,0)->1
(1,1,1)->0
```

完成本 step 的可见结果：8 个 case 全部通过。

## Step 8：实现 residual masses 和 threshold

对于 pair `(2,3)`，两个 assigned cubic terms 给出：

```text
A23(x) = 5*x1 - 4*x4
C23+ = 5
C23- = 4
T23 = 5
M23 = 6
```

对于 pair `(1,4)`：

```text
A14(x) = 2*x5
C14+ = 2
C14- = 0
T14 = 2
M14 = 3
```

实现时不要把 threshold 错写成：

```text
sum of absolute coefficients
```

本例 pair `(2,3)` 的正确 threshold 是 `max(5,4)=5`，不是 `5+4=9`。

还要区分：

- `M=T`：pointwise value exact，但可能有 inconsistent auxiliary tie；
- `M>T`：consistent auxiliary 对每个固定 `x` 都唯一。

完成本 step 的可见结果：四个 masses、两个 thresholds 和两个 strict penalties 都逐项通过 assertion。

## Step 9：实现 selective encoding

使用一个 auxiliary `y23`：

```text
F_sel(x,y23)
= g(x)
  + 5*x1*y23
  - 4*y23*x4
  + 2*x1*x4*x5
  + M23*P_R(x2,x3,y23)
```

其中 `g(x)` 见手算表。

对每个原始 `x`：

1. 分别计算 `y23=0` 和 `y23=1` 的 encoded value；
2. 取两者最小值；
3. 与原始 `f(x)` 比较；
4. 记录所有达到最小值的 `y23`；
5. 在 `M23=6` 时断言唯一 minimizer 等于 `x2*x3`。

建议测试逻辑：

```python
for x in all_32_assignments:
    values = {y: F_sel(x, y, M23=6) for y in (0,1)}
    minimum = min(values.values())
    minimising_y = [y for y,v in values.items() if v == minimum]

    assert minimum == f(x)
    assert minimising_y == [x2*x3]
```

完成本 step 的可见结果：32 个 `x` 上 mismatch 为 0，并且所有 consistent auxiliaries 唯一。

## Step 10：测试 selective penalty 的 sharp boundary

分别测试 `M23=4,5,6`：

```text
M23=4: 必须找到 pointwise mismatch witness
M23=5: 0 pointwise mismatch，但必须找到 auxiliary tie witness
M23=6: 0 pointwise mismatch、0 tie、consistent auxiliary 始终唯一
```

显式断言 witness：

```text
x=(1,1,1,0,0)
consistent y23=1

M23=4: F(y=0)=4 < F(y=1)=5=f(x)
M23=5: F(y=0)=F(y=1)=5=f(x)
M23=6: F(y=0)=6 > F(y=1)=5=f(x)
```

不要只写 `assert test_returns_true`；失败时保存/显示 witness。

完成本 step 的可见结果：程序真实观察到 fail、tie、unique 三种不同状态。

## Step 11：实现 fully quadratized encoding

使用 `y23` 和 `y14`：

```text
F_full(x,y23,y14)
= g(x)
  + 5*x1*y23
  - 4*y23*x4
  + 2*y14*x5
  + 6*P_R(x2,x3,y23)
  + 3*P_R(x1,x4,y14)
```

对每个原始 `x` 枚举四个 auxiliary assignments：

```text
(y23,y14) in {(0,0),(0,1),(1,0),(1,1)}
```

断言：

```text
min_(y23,y14) F_full(x,y23,y14) == f(x)
unique minimiser == (x2*x3, x1*x4)
```

再单独对 pair `(1,4)` block 测试：

```text
M14=1 -> failure witness exists
M14=2 -> exact value but tie exists
M14=3 -> exact and consistent auxiliary unique
```

完成本 step 的可见结果：full encoding 在全部 32 个 `x` 上 mismatch 为 0，consistent auxiliary pair 始终唯一。

## Step 12：验证 logical metrics

从生成的 encodings 中计算或至少 golden-assert：

| Encoding | Variables | Auxiliaries | Retained cubics | Distinct quadratic couplings |
|---|---:|---:|---:|---:|
| Native | 5 | 0 | 3 | 3 |
| Selective | 6 | 1 | 1 | 7 |
| Full | 7 | 2 | 0 | 11 |

Quadratic couplings 按 coefficient aggregation 后的不同 degree-two supports 计数，而不是按表达式中出现次数计数。

完成本 step 的可见结果：五列数据与表格一致。

## Step 13：输出最终摘要并提交给 Benchmark 负责人

测试最终至少应证明：

```text
canonical coefficients match: PASS
assignments checked: 32
direct-vs-canonical mismatches: 0
selective pointwise mismatches: 0
full pointwise mismatches: 0
M23=4 failure witness found: PASS
M23=5 tie witness found: PASS
M23=6 unique consistency: PASS
M14=1 failure witness found: PASS
M14=2 tie witness found: PASS
M14=3 unique consistency: PASS
original optimum: 0
number of original minimisers: 21
```

请回传：

1. 测试文件或 commit；
2. 精确运行命令；
3. 完整测试输出；
4. 如果有任何不一致，给出最小失败 witness：`x`、auxiliary、direct value、encoded value；
5. 本轮是否做了任何手算表之外的定义选择。如果有，请标为 `decision needed`，不要静默固定。

## 本轮结束后的下一步

只有本 golden example 全部通过后，才开始：

```text
Benchmark 负责人：A0 benchmark_spec.md
代码负责人：C0 repository/config/result schema
双方共同：instance_schema v0.1 和字段语义确认
```

