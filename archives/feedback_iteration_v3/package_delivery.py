from pathlib import Path
import hashlib,json,shutil,zipfile
B=Path(__file__).resolve().parent;out=B/'deliverables';out.mkdir(exist_ok=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
# A small addendum can be imported without overwriting an existing main.tex.
small=out/'URSS_Iteration_v3_Paper_Addendum.zip'
readme='''# 导入论文补充段落\n\n本包不包含替换原稿的 main.tex。上传并保留 iteration_v3/ 子目录，在需要的位置加入：\n\n\\input{iteration_v3/paper_addendum.tex}\n\n原稿需已加载 amsmath、booktabs、graphicx。插入前由作者审阅主预算零结果、次要网格案例、guardrail 未改变选择及经典对照限制。\n\n正文和两张图都来自此次新实验。此段未自动合入现有论文，也未更新线上 Overleaf。\n'''
with zipfile.ZipFile(small,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 tex=(B/'paper_addendum.tex').read_text().replace('{figures/','{iteration_v3/figures/')
 z.writestr('iteration_v3/paper_addendum.tex',tex)
 z.writestr('README_IMPORT.md',readme)
 for p in sorted((B/'figures').glob('*.png')):z.write(p,'iteration_v3/figures/'+p.name)
files=[]
for p in sorted(B.rglob('*')):
 if not p.is_file():continue
 rel=p.relative_to(B)
 if any(part in {'__pycache__','preview','deliverables'} for part in rel.parts):continue
 if p.name in {'SHA256SUMS.json','RUNNING.lock'} or p.suffix=='.zip':continue
 files.append(p)
manifest={p.relative_to(B).as_posix():sha(p) for p in files}
(B/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
full=out/'URSS_Feedback_Iteration_v3.zip'
with zipfile.ZipFile(full,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for p in files+[B/'SHA256SUMS.json']:z.write(p,p.relative_to(B).as_posix())
with zipfile.ZipFile(full) as z:
 for name,h in manifest.items():
  if hashlib.sha256(z.read(name)).hexdigest()!=h:raise RuntimeError('Packaged hash mismatch: '+name)
shutil.copy2(B/'URSS_Feedback_Iteration_v3_Report.md',out/'URSS_Feedback_Iteration_v3_Report.md')
checks={'status':'PASS','zip_files':len(files)+1,'deliverables':{p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in [full,small,out/'URSS_Feedback_Iteration_v3_Report.md']}}
(out/'delivery_manifest.json').write_text(json.dumps(checks,indent=2)+'\n')
print(json.dumps(checks,indent=2))
