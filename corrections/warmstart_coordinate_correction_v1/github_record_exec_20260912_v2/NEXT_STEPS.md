# 后续行动：代码归档、GitHub、Overleaf

本轮 4,800 个实验任务已经完成。此操作包仅导入已完成的修复和结果，并运行 26 个合成回归测试；不会重跑正式实验。

## 1. 准备文件

将以下两个 ZIP 下载到 Downloads：

- URSS_WARMSTART_CORRECTION_EXECUTED_v1.zip：此前的完整结果包，保持原始字节。
- URSS_NEXT_ACTIONS_v1.zip：本操作包，解压即可。

在你的实际 Git 项目“协作”根目录打开 PowerShell。这个目录应包含 urss_pipeline、configs 和 .git。无需把完整结果包复制进仓库。

## 2. 导入并测试

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\URSS_NEXT_ACTIONS_v1\START_HERE.ps1" -Phase prepare -Repo .
```

上述路径假设操作包直接解压在 Downloads 下。若解压到了别处，修改 -File 后的路径。ExecutionPolicy Bypass 只作用于这次 PowerShell 子进程，不修改系统策略。

prepare 会：

1. 校验完整结果 ZIP 的 SHA-256、4,800 个任务身份和结果计数。
2. 检查现有代码是否为原已审计版本或相同修复版本。未知改动会报 BLOCKED，供人工合并，不覆盖它们。
3. 从当前 HEAD 创建新分支，并在用户目录的 urss_ws 下创建路径较短的独立 Git worktree，保留原工作目录的已暂存、未暂存和未跟踪内容。其他未提交修改不会自动进入新分支。
4. 导入 7 个修复/执行器/测试文件，以及约数 MB 的结果与审计索引。全部证据仍保存在原始 ZIP 中。
5. 使用原项目的 .venv 运行 26 个合成 mixer/执行器测试；无 .venv 时使用启动脚本的 Python。可以用 -Python 指定环境，不自动安装依赖。
6. 暂存精确文件清单，并检查暂存字节与导入版本一致。正式 paper/main.tex 保持原状，论文材料放在 correction 记录内。

若原项目代码已发生其他改变，或测试缺少依赖，保留输出的 BLOCKED 和日志，先解决该具体问题。结果不是根据优势是否显著来决定导入。

## 3. Commit 和 push

prepare 输出 `PREPARE: PASS`、`WORKTREE` 和 `BRANCH`。把输出中的工作目录填入下列变量：

```powershell
$wt = '粘贴 prepare 输出的 WORKTREE 完整路径'
$helper = "$env:USERPROFILE\Downloads\URSS_NEXT_ACTIONS_v1\START_HERE.ps1"
git -C $wt diff --cached --stat
powershell -NoProfile -ExecutionPolicy Bypass -File $helper -Phase commit -Worktree $wt
```

commit 会重新核对准备后的文件和 Git 暂存区，再创建本地提交；若文件有改动则停止。保存 `INTEGRATION_COMMIT`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $helper -Phase push -Worktree $wt
```

push 只推送这条新分支到 rrocy6/urss-selective-locality-reduction 的 origin，不做 force push 或自动 merge。现有 Git 登录配置会照常使用。认证失败时修复 Git 登录后重试 push。

GitHub 上为新分支创建 PR，base 选你目前使用的研究分支（按已上传快照为 four-part-addendum-v1；若项目已换分支，选当前实际目标）。确认代码差异和测试日志，再按协作约定合并。

## 4. 保存完整结果包

在 GitHub 的 Releases 页面创建 draft release，创建一个新的 correction tag，并选择刚才推送的分支。粘贴本包 RELEASE_NOTES.md，上传原始 40.8 MB 结果 ZIP。核对 tag 指向的提交、ZIP 文件名和 SHA-256 后发布。

GitHub 网页普通文件上传的大小限制不适合这个结果包，使用 Release 附件。完整 ZIP 中的 binding 和执行 commit 均保留原值；仓库 integration commit 与历史 execution commit 的对应关系见 GITHUB_INTEGRATION.json，不能把历史 code_commit 改成新提交。

## 5. 最新 Overleaf 合稿

从当前正在使用的 Overleaf 项目下载完整源码 ZIP，再上传到对话中。包括 main.tex、所有 input/include 的 .tex、参考文献、图片及项目自带的 class/style 文件。

quantumarticle.cls 是排版类文件。若项目已有该文件，优先保留当前版本；需要补充时可从官方地址下载并与 main.tex 放在一起：

https://raw.githubusercontent.com/quantum-journal/quantum-journal/master/quantumarticle.cls

后续合稿包括 beta 坐标、warm-start 表图、Results/Discussion/Conclusion、来源说明和全文旧结论清理。旧快照修改稿不能直接覆盖最新 main.tex。

## 6. 单独立项的后续核验

Table 13/kappa、margin sensitivity、beam/Pareto/pruning、E3/E6 汇总和 E5 标签依照被冻结的新计划分别处理。需先将最新论文中的具体结论对应到实际运行版本和数据，再决定是否补实验。不要现在自行更改参数或启动这些重跑。

参考：

- Git worktree：https://git-scm.com/docs/git-worktree
- GitHub Releases：https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- Quantum class：https://github.com/quantum-journal/quantum-journal#installation-and-usage
