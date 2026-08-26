# Section 7.1.1 五变量 Max-3SAT：手算检查表

用途：这是 Benchmark 负责人交给代码负责人的数学真值表。代码测试应逐项复现这里的结果。

## 0. 固定约定

- 原始变量：`x1,...,x5 in {0,1}`。
- `xi=1` 表示 Boolean variable `xi` 为真，`xi=0` 表示为假。
- 优化方向：最小化被违反 clause 的总权重。
- 正 literal `xi` 的 false indicator 是 `1-xi`。
- 负 literal `not xi` 的 false indicator 是 `xi`。
- 一个三 literal OR clause 只有在三个 literal 全部为假时才被违反，因此 clause violation indicator 等于三个 false indicators 的乘积。
- polynomial 必须使用 Boolean multilinear/canonical 形式；support 内变量排序，重复 support 的系数相加，系数聚合为 0 的项删除。

## 1. 原始实例

| Clause | Weight | 三个 literals |
|---|---:|---|
| C1 | 5 | `not x1 OR not x2 OR not x3` |
| C2 | 4 | `x2 OR x3 OR x4` |
| C3 | 2 | `not x1 OR not x4 OR not x5` |

## 2. Clause 到 violation polynomial

### C1

三个 literals 都是负 literal：

| Literal | 什么时候为假 | False indicator |
|---|---|---|
| `not x1` | `x1=1` | `x1` |
| `not x2` | `x2=1` | `x2` |
| `not x3` | `x3=1` | `x3` |

所以：

```text
P_C1(x) = x1*x2*x3
w1*P_C1(x) = 5*x1*x2*x3
```

### C2

三个 literals 都是正 literal：

| Literal | 什么时候为假 | False indicator |
|---|---|---|
| `x2` | `x2=0` | `1-x2` |
| `x3` | `x3=0` | `1-x3` |
| `x4` | `x4=0` | `1-x4` |

所以：

```text
P_C2(x) = (1-x2)*(1-x3)*(1-x4)
w2*P_C2(x) = 4*(1-x2)*(1-x3)*(1-x4)
```

### C3

三个 literals 都是负 literal：

| Literal | 什么时候为假 | False indicator |
|---|---|---|
| `not x1` | `x1=1` | `x1` |
| `not x4` | `x4=1` | `x4` |
| `not x5` | `x5=1` | `x5` |

所以：

```text
P_C3(x) = x1*x4*x5
w3*P_C3(x) = 2*x1*x4*x5
```

### 未展开的原始目标

```text
f(x) = 5*x1*x2*x3
     + 4*(1-x2)*(1-x3)*(1-x4)
     + 2*x1*x4*x5
```

## 3. 展开 C2

先展开前两个因子：

```text
(1-x2)*(1-x3) = 1 - x2 - x3 + x2*x3
```

再乘 `1-x4`：

```text
(1 - x2 - x3 + x2*x3)*(1-x4)
= 1 - x2 - x3 + x2*x3
  - x4 + x2*x4 + x3*x4 - x2*x3*x4
```

整理并乘权重 4：

```text
4*(1-x2)*(1-x3)*(1-x4)
= 4
  - 4*x2 - 4*x3 - 4*x4
  + 4*x2*x3 + 4*x2*x4 + 4*x3*x4
  - 4*x2*x3*x4
```

## 4. Canonical PUBO

因此完整目标为：

```text
f(x) = 4
     - 4*x2 - 4*x3 - 4*x4
     + 4*x2*x3 + 4*x2*x4 + 4*x3*x4
     + 5*x1*x2*x3 - 4*x2*x3*x4 + 2*x1*x4*x5
```

代码使用 coefficient dictionary 时，期望结果为：

| Canonical support | Coefficient |
|---|---:|
| `()` | 4 |
| `(2,)` | -4 |
| `(3,)` | -4 |
| `(4,)` | -4 |
| `(2,3)` | 4 |
| `(2,4)` | 4 |
| `(3,4)` | 4 |
| `(1,2,3)` | 5 |
| `(2,3,4)` | -4 |
| `(1,4,5)` | 2 |

检查项：

- [ ] support 内变量严格排序；
- [ ] constant 使用空 support `()`；
- [ ] 一共有 10 个非零 canonical terms；
- [ ] degree 为 3；
- [ ] cubic support 在 coefficient aggregation 之后重新计算。

## 5. Cubic support、pair shadow 和 reuse

三体 support 为：

```text
C3(f) = {(1,2,3), (2,3,4), (1,4,5)}
```

每个 cubic support 的三个 constituent pairs：

| Cubic support | Coefficient | Candidate pairs |
|---|---:|---|
| `(1,2,3)` | 5 | `(1,2)`, `(1,3)`, `(2,3)` |
| `(2,3,4)` | -4 | `(2,3)`, `(2,4)`, `(3,4)` |
| `(1,4,5)` | 2 | `(1,4)`, `(1,5)`, `(4,5)` |

因此：

```text
pair shadow = {(1,2),(1,3),(2,3),(2,4),(3,4),(1,4),(1,5),(4,5)}
pair-shadow size = 8
d(2,3) = 2
all other d(p) = 1
Delta_2 = max_p d(p) = 2
```

`(2,3)` 同时覆盖前两个 cubic terms，所以它是可复用 pair。第三个 cubic term 不与前两个共享任何 pair。

若全部二次化，最小 pair cover 大小为：

```text
tau_2 = 2
```

理由：一个 `(2,3)` 可覆盖前两个 cubic supports，但第三个还需要 `(1,4)`、`(1,5)` 或 `(4,5)` 中的一个；不可能只用一个 pair 覆盖三个 cubic supports。

## 6. Rosenberg penalty

定义：

```text
P_R(a,b,y) = a*b - 2*a*y - 2*b*y + 3*y
```

目标是强制 `y=a*b`。完整真值表如下：

| a | b | y | a*b | P_R | y 是否一致 |
|---:|---:|---:|---:|---:|---|
| 0 | 0 | 0 | 0 | 0 | 是 |
| 0 | 0 | 1 | 0 | 3 | 否 |
| 0 | 1 | 0 | 0 | 0 | 是 |
| 0 | 1 | 1 | 0 | 1 | 否 |
| 1 | 0 | 0 | 0 | 0 | 是 |
| 1 | 0 | 1 | 0 | 1 | 否 |
| 1 | 1 | 0 | 1 | 1 | 否 |
| 1 | 1 | 1 | 1 | 0 | 是 |

必须满足：

```text
P_R >= 0
P_R = 0 if and only if y = a*b
```

## 7. Selective encoding

选择：

- 将 `(1,2,3)` 和 `(2,3,4)` 分配给共享 pair `(2,3)`；
- 保留 `(1,4,5)` 为 native cubic term；
- 引入 `y23=x2*x3`。

degree-at-most-two 部分为：

```text
g(x) = 4
     - 4*x2 - 4*x3 - 4*x4
     + 4*x2*x3 + 4*x2*x4 + 4*x3*x4
```

替换后的 shared residual：

```text
A23(x) = 5*x1 - 4*x4
```

正、负 coefficient masses：

```text
C23+ = 5
C23- = 4
T23  = max(C23+, C23-) = 5
```

解释：当 `x1=1,x4=0` 时，`A23` 最大为 5；当 `x1=0,x4=1` 时，`A23` 最小为 -4。因此 infinity norm 是 5。

非严格 exact threshold 是 `M23=5`。为保证对每个固定的原始 `x`，consistent auxiliary `y23=x2*x3` 是唯一最优值，样例使用 strict margin：

```text
M23 = 6
```

Selective objective：

```text
F_sel(x,y23)
= g(x)
  + 5*x1*y23
  - 4*y23*x4
  + 2*x1*x4*x5
  + 6*P_R(x2,x3,y23)
```

期望 pointwise identity：

```text
for every x in {0,1}^5:
    f(x) = min over y23 in {0,1} of F_sel(x,y23)
```

## 8. Fully quadratized encoding

再将第三个 cubic term 分配给 pair `(1,4)`，引入：

```text
y14 = x1*x4
```

其 residual 和 threshold 为：

```text
A14(x) = 2*x5
C14+ = 2
C14- = 0
T14  = 2
M14  = 3   # strict positive margin
```

Fully quadratized objective：

```text
F_full(x,y23,y14)
= g(x)
  + 5*x1*y23
  - 4*y23*x4
  + 2*y14*x5
  + 6*P_R(x2,x3,y23)
  + 3*P_R(x1,x4,y14)
```

期望 pointwise identity：

```text
for every x in {0,1}^5:
    f(x) = min over (y23,y14) in {0,1}^2 of F_full(x,y23,y14)
```

## 9. Penalty 边界的预期行为

### Pair `(2,3)`

| M23 | Pointwise exact? | Consistent auxiliary 是否始终唯一？ | 预期现象 |
|---:|---|---|---|
| 4 | 否 | 否 | 至少存在一个低于原始目标的 inconsistent witness |
| 5 | 是 | 否 | 保持目标值，但某些 `x` 出现 consistent/inconsistent tie |
| 6 | 是 | 是 | 0 mismatch、0 tie，consistent `y23=x2*x3` 唯一 |

可用于测试的 witness：

```text
x = (x1,x2,x3,x4,x5) = (1,1,1,0,0)
f(x) = 5
consistent y23 = x2*x3 = 1

when M23=4:
    F_sel(x,y23=0) = 4
    F_sel(x,y23=1) = 5
    inconsistent y23=0 错误地更优，所以不 exact

when M23=5:
    F_sel(x,y23=0) = 5
    F_sel(x,y23=1) = 5
    目标值仍 exact，但出现 tie

when M23=6:
    F_sel(x,y23=0) = 6
    F_sel(x,y23=1) = 5
    consistent y23=1 唯一更优
```

### Pair `(1,4)` 的 isolated block

对 `2*x1*x4*x5 -> 2*y14*x5 + M14*P_R(x1,x4,y14)`：

| M14 | Pointwise exact? | Consistent auxiliary 是否始终唯一？ |
|---:|---|---|
| 1 | 否 | 否 |
| 2 | 是 | 否，存在 tie |
| 3 | 是 | 是 |

witness 可取 `x1=x4=x5=1`：`M14=1` 时 inconsistent `y14=0` 给出 1，小于原始值 2；`M14=2` 时两者同为 2；`M14=3` 时 consistent `y14=1` 唯一最优。

## 10. Logical metrics 的预期结果

| Encoding | Total variables | Auxiliaries | Retained cubic terms | Distinct quadratic couplings | Penalties |
|---|---:|---:|---:|---:|---|
| All-native | 5 | 0 | 3 | 3 | none |
| Selective | 6 | 1 | 1 | 7 | `M23=6` |
| Fully quadratized | 7 | 2 | 0 | 11 | `M23=6, M14=3` |

注意：这个表只比较 logical representation，不能据此宣称 selective 的 QAOA 或 compiled circuit 一定更好。

## 11. 最终验收数字

完整枚举应得到：

```text
number of original assignments = 32
direct-vs-canonical mismatches = 0
selective pointwise mismatches at M23=6 = 0
full pointwise mismatches at M23=6,M14=3 = 0
original optimum = 0
number of original minimisers = 21
```

双方签字检查：

- [ ] 我已独立复算 clause indicators 与展开；
- [ ] 代码负责人得到完全相同的 canonical coefficient 表；
- [ ] direct evaluator 与 canonical evaluator 在 32 个 `x` 上一致；
- [ ] selective/full exactness tests 全部通过；
- [ ] threshold 下方、等号和 strict margin 三种行为均被自动测试；
- [ ] 如果出现差异，已记录具体 assignment、两边数值和定义原因；
- [ ] 测试不使用 notebook 隐藏状态。

