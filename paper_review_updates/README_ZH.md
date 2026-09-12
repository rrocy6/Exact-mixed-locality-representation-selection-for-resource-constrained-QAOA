# 合入 URSS_project (6).pdf 对应新版源码

此目录是修改片段与结果文件，不是完整 Overleaf 项目。请在最新 Overleaf 源码中按 PDF 的 D01–D08 标签定位，合入 REVIEW_RESOLUTION.tex 的相应段落，并处理 A01–A03。不要将本目录的片段命名为 main.tex。

- 第 7 页 Table 3：D04_table3.tex；只需 Gates/Depth 时从完整表保留相应列。
- 第 8 页 Table 5：D05_table5.tex。
- 第 51 页 Table 17：κ 两个 selective 中位数改为 spin glass 4.5、Max-3SAT 57.5；依据 prior_closeout 的 kappa_table16_medians.csv。旧版输出名中的 table16 对应本 PDF 的 Table 17。
- 第 59 页 Table 23：D08_table23.tex；数值与本 PDF 现有实例级汇总一致。
- D04_D05_resources_corrected.pdf：冻结设计按正确顺序重聚合的资源图。
- D08_e3_diagnostics.pdf：E3 次级诊断，实例级 Student-t 区间，可作为 Figure 7 的重生成数据图。
- D08_e6_noise.pdf：E6 绝对目标值与实例级 Student-t 区间。
- figure_e5_regime_map_2d.pdf：第一轮已修正的 E5 图，可对照新版 Figure 1；正文补齐“little effect 含不确定性”。

这些表图描述历史冻结设计及其后处理。新 selector 的验证结果见 oracle_repaired_validation.csv、sensitivity_repaired_summary.csv；其改变的设计不能直接继承旧 QAOA 观测值。SELECTED_RERUN_REQUIRED.csv 给出必须重新建立任务计划的旧行，原始文件保留。

表片段为 tabular 环境。放入现有 table 环境；宽表可使用已加载 graphicx 的 \resizebox{\linewidth}{!}{\input{D05_table5.tex}}。保留现有 caption/label，重编译检查引用及布局。仅凭 PDF 无法保证这些片段与当前 main.tex 的宏和标签完全匹配。
