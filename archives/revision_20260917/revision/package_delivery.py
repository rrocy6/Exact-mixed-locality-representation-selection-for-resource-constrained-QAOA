from pathlib import Path
import hashlib, json, shutil, zipfile

ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/'output'
OUT.mkdir(exist_ok=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def scientific_files(folder):
    for p in folder.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ['.pyc','.log']:
            yield p

def overleaf_files():
    for p in scientific_files(ROOT/'overleaf'):
        if p.parent==ROOT/'overleaf' and p.name in ['main.pdf','main.aux','main.log','main.out','main.synctex.gz']:
            continue
        yield p

overleaf=OUT/'URSS_Overleaf_revised_20260917.zip'
with zipfile.ZipFile(overleaf,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(overleaf_files()):z.write(p,p.relative_to(ROOT/'overleaf').as_posix())

code=OUT/'URSS_code_and_evidence_20260917.zip'
files=[]
for directory in ['experiments','qaoa_new','theory','manuscript_sections','code/source/urss_pipeline','code/source/data/raw']:
    files.extend(scientific_files(ROOT/directory))
files.extend(overleaf_files())
for name in ['main.original.tex','overleaf_original_hashes.json','revise_manuscript.py','validate_delivery.py',
             'build_resource_supplement.py','delivery_validation.json','修改说明与审核结论.md','package_delivery.py']:
    files.append(ROOT/name)
with zipfile.ZipFile(code,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(set(files)):z.write(p,'revision/'+p.relative_to(ROOT).as_posix())
    z.write(ROOT/'README_REPRODUCE.md','README_REPRODUCE.md')
    z.write(ROOT/'requirements-revision.txt','requirements-revision.txt')
    z.writestr('MANIFEST_SHA256.json',json.dumps({'revision/'+p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(files))},indent=2))

shutil.copyfile(ROOT/'overleaf/main.pdf',OUT/'URSS_revised_manuscript_20260917.pdf')
shutil.copyfile(ROOT/'修改说明与审核结论.md',OUT/'修改说明与审核结论.md')
for path in [overleaf,code]:
    with zipfile.ZipFile(path) as z:assert z.testzip() is None
results={p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in [overleaf,code,OUT/'URSS_revised_manuscript_20260917.pdf',OUT/'修改说明与审核结论.md']}
(OUT/'DELIVERY_MANIFEST.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(results,indent=2,ensure_ascii=True))
