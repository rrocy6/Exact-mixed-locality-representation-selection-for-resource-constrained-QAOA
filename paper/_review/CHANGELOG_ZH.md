# 最新 Overleaf 稿：warm-start 合稿记录

本次以用户上传的 URSS_project (3).zip 为原稿，完成 warm-start 专项合稿并编译为 59 页。没有在本轮重新运行正式实验，没有直接写入在线 Overleaf，也没有替用户提交本次论文修改到 GitHub。

## 已完成

| 位置 | 修改与验证 |
|---|---|
| Abstract / Introduction | 保留 targeted Max-3SAT 改善；将 pair 的额外收益限定到与 independence 的比较，避免遮蔽 p=2 的 original-only 对比 |
| §5.2 与 Appendix C | 统一 cold 的 exp(-i beta X) 优化器坐标；warm 写为 exp(+i beta H_M)，physical_beta=-optimizer_beta；Rz(2 beta) 与全部因子同步 |
| §7 与 Appendix G.4 | 固定全部 original/aux 概率 1/2 的 null-control，说明 independence 在仅原变量 1/2 时会给 aux 1/4；区分初始化区间和优化边界 |
| §8.4、Table 8（第22页） | 用 480 条 corrected targeted 结果替换旧数据；36 个两表配对 CI 单元格均由已绑定的汇总核对 |
| Appendix H.6、Table 19（第56页） | 用 4,320 条 corrected original E4 记录的汇总替换旧表；标记 n=2/7 与零层 n0=2/2 |
| Figure 10（第57页） | 更新三种 warm 政策相对 cold 的 targeted 性能图，使用实例级 Student-t 区间 |
| Figure 8（第56页） | 新增 original E4 主要 pair-minus-cold 比较图 |
| §9.3 / §9.4 / Conclusion | 同步主要与额外比较、环境变化的解释边界；明确 CI 含零不等于等效 |
| Appendix F.1 | 修正“500 个实例/每 family”为每 family 安排500次生成尝试；567条归档候选不代表1000次生成全部成功 |
| Appendix F.4、Data/code availability、Table 9 | 区分历史资料、修正结果和 Git 集成；原 execution commit 不改写为 d9f5de9；注明完整原始包 Release 尚待发布 |
| 模板与排版 | 补入官方 quantumarticle.cls v6.1；全文编译成功，修复两处文字越界，保留原作者、结构和其余实验结果 |

原图中仅 figure_strong_bias_warmstart.pdf 被替换；其余8张已有图保持原始字节。新增1张 original E4 图。LP输入不变，所以两张LP信号图保留原版。

## 结果解释

- Targeted Max-3SAT 的 pair-minus-cold：p=1 为 -6.7198 [-9.2712,-4.1683]，p=2 为 -6.7971 [-9.1395,-4.4547]。结论仅适用于原signal-enriched子集。
- Targeted Max-3SAT 的 pair-minus-original-only 在 p=2 为 -0.4759 [-0.8454,-0.1063]；p=1不明确。pair-minus-independence在两个深度都不明确。
- 原 E4 八个主要 pair-minus-cold 区间都含零；旧数据按相同Student-t方法复算也都含零。
- 4,332条任务重新优化，468条零层初态验证复用；这批实验是在此前绑定的执行环境完成，非本轮合稿重新运行。数值环境不同，新旧结果变化不能全部归于mixer。

## 编译与可复核性

- 编译器：pdfLaTeX，TeX Live 2023，latexmk；59页。
- 无未定义引用/引文、重复标签、缺字或overfull boxes。
- 剩余一条caption包识别quantumarticle的提示，使用默认设置；标题和原参考文献处有少量underfull行距提示。未隐藏这些提示。
- 全文59页已用缩略图检查；修改的公式、表图和分页另以较高分辨率检查。
- 当前源码本来已没有重复section/subsection标题，也没有“尚无branch-and-bound traces”或“所有sensitivity需未来运行”的旧声明；本次没有再次插入重复段落。
- correction_sources/保留绑定审计、执行信息、完整60项主要配对汇总和描述统计；没有修改任何原执行证据。
- _review/保留原main.tex文本、差异补丁、编译日志和VALIDATION.json；SHA256_MANIFEST.csv排除自身及外部sidecar，避免递归自哈希。

## 尚未完成，不能据此标记整篇论文最终通过

| 项目 | 当前证据 | 后续动作 |
|---|---|---|
| κ／先前称作Table 13的诊断 | 当前label为tab:e2-selector-diagnostics，实际是Table 16（第51页）。正文定义排除identity，归档reference_compiler.py的动态范围计算包含所有非零Pauli系数，口径不同；表中7.25、346仍保留历史值并加源码注释 | 独立编号amendment，按非恒等Pauli项重算并核对所有派生表；若仅诊断变化，不自动重跑QAOA |
| margin sensitivity | 当前Table 14（第48页），label为tab:selector-sensitivity-addendum。0.5和2.0各60条pass；actions变化5和7可从原CSV复算。已检查的addendum代码将margin传入candidate与normalisation | 独立核验实际编码/penalties/score/feasibility及design影响；不能据本次行数复核宣称整项算法已通过，也不能沿用旧main分支问题自动要求重跑 |
| beam/Pareto/pruning、E3/E6、E5 | 本次只做warm-start文字与文件整合 | 按冻结计划后续逐项核验，未标记PASS |
| Acknowledgements / Author contributions | 原稿为空，仅有TODO | 由作者提供真实致谢、资助与贡献，不虚构 |
| GitHub PR / 完整原始包Release | 用户日志证明d9f5de9提交和新分支push成功 | PR合并与Release发布尚无完成证据；本次main.tex修改也尚未commit/push |

## 放回 Overleaf

1. 在Overleaf项目列表选择 New Project → Upload Project，上传更新后的源码ZIP，可先作为一份新项目检查。
2. 将main.tex设为主文件，编译器选择pdfLaTeX，然后Recompile。Overleaf常规TeX环境提供algorithm与algorithmicx；本包补入了缺少的quantumarticle.cls。
3. 如需合入原在线项目：按相同相对路径更新main.tex、output/pdf/figure_strong_bias_warmstart.pdf，新增output/pdf/figure_original_e4_warmstart_corrected.pdf和quantumarticle.cls。保留correction_sources/作为数据来源；_review/供核对，不被正文input。
4. 若上传本包后原项目又有新修改，先用_review/main_warmstart_integration.patch核对合并。当前包的原稿hash在VALIDATION.json中。

官方模板来源：https://github.com/quantum-journal/quantum-journal
