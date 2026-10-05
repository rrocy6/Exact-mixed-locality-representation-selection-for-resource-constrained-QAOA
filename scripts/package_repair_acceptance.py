"""Build two ZIP64 packages from explicit project paths, with hashed manifests."""
import csv
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def csv_bytes(rows,fields):
    f=io.StringIO(newline='');w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows);return f.getvalue().encode()
def eligible(p):return p.is_file() and not set(p.parts)&{'.git','.venv','__pycache__','.pytest_cache'} and p.suffix.lower() not in {'.zip','.pyc','.pyo'}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--session',default='P1_PACKAGING_SESSION.json');args=parser.parse_args()
    session=read(ROOT/args.session);out=ROOT/session['delivery_dir'];coverage=ROOT/session['coverage_dir'];cor=ROOT/'corrections/review_v2_20260920';stamp=session['stamp']
    if out.exists():raise ValueError('New delivery directory required')
    out.mkdir(parents=True)
    source=set();evidence=set();omitted=[]
    for directory in ('scripts','urss_pipeline','tests','golden_example','configs','instance_schema','data','paper','fibre_selector_v2'):
        source.update(p for p in (ROOT/directory).rglob('*') if eligible(p))
    source.update(p for p in ROOT.iterdir() if eligible(p) and p.suffix.lower() in {'.py','.md','.txt','.json','.yaml','.sha256'} and p.name!='FILE_MANIFEST.csv')
    source.add(ROOT/'BASE_FILE_MANIFEST.csv')
    original=ROOT/'results/multiseed_20260918T163717Z'
    source.update(p for p in (original/'inputs').rglob('*') if eligible(p))
    for name in ('candidate_manifest.csv','instance_manifest.csv','experiment_config.json','experiment_config.yaml','INPUT_COPY_MANIFEST.json'):
        source.add(original/name)
    source.update(cor.glob('requirements-*-lock.txt'));source.add(ROOT/session['full_run']/'requirements-p1-lock.txt')
    evidence.update(p for p in cor.rglob('*') if eligible(p) and 'review_input' not in p.parts)
    evidence.update(p for p in original.rglob('*') if eligible(p) and p not in source)
    # Historical FAIL audit is immutable and carried with the acceptance evidence.
    evidence.update(p for p in (ROOT/'audit').rglob('*') if eligible(p))
    evidence.update(ROOT/n for n in ('FIX_REPORT.md','P1_COVERAGE_AND_PACKAGING_REPORT.md','DELIVERY_README.md','BASE_ARCHIVE_REQUIREMENTS.json','P1_PACKAGING_SESSION.json',args.session))
    for p in sorted(source|evidence):
        if p.stat().st_size>50*1024**2:
            relative=p.relative_to(ROOT).as_posix()
            if 'robust_regions.csv' not in p.name:raise ValueError('Unreviewed necessary large file: '+relative)
            legacy=relative.startswith('results/')
            omitted.append({'path':relative,'size_bytes':p.stat().st_size,'sha256':sha(p),
                'purpose':'expanded per-budget table' if not p.name.startswith('.') else 'historical interrupted temporary table',
                'reason':'reproducible expanded detail; all resource vectors and compact arrays retained' if not legacy else 'legacy redundant table or interrupted temporary file; not used for acceptance',
                'rebuild_command':'python -X utf8 -B scripts/multiseed_experiment.py --stage analyze --run-dir results/multiseed_20260918T163717Z --output-dir corrections/regenerated_budget_detail' if not legacy else 'restore exact historical bytes from named base archive if required',
                'dependencies':'source+evidence packages; NumPy' if not legacy else 'BASE_ARCHIVE_REQUIREMENTS.json (not needed for core acceptance)'})
            source.discard(p);evidence.discard(p)
    (out/'OMITTED_LARGE_FILES.csv').write_bytes(csv_bytes(omitted,['path','size_bytes','sha256','purpose','reason','rebuild_command','dependencies']))
    # Deduplicate byte-identical evidence only. Source remains directly runnable.
    canonical={};hashes={};duplicate=[]
    for p in sorted(source):
        hashes[p]=sha(p);canonical.setdefault((p.stat().st_size,hashes[p]),p)
    kept=set()
    for p in sorted(evidence,key=lambda p:(not p.is_relative_to(original),p.as_posix())):
        hashes.setdefault(p,sha(p));k=(p.stat().st_size,hashes[p])
        if p in source:continue
        if k in canonical:
            duplicate.append({'path':p.relative_to(ROOT).as_posix(),'source_path':canonical[k].relative_to(ROOT).as_posix(),'size_bytes':k[0],'sha256':k[1]})
        else:canonical[k]=p;kept.add(p)
    evidence=kept
    duplicate_data=csv_bytes(duplicate,['path','source_path','size_bytes','sha256'])
    (out/'DUPLICATE_FILE_MAP.csv').write_bytes(duplicate_data)
    with (ROOT/'BASE_FILE_MANIFEST.csv').open(encoding='utf-8-sig',newline='') as f:baseline={r['path']:r for r in csv.DictReader(f)}
    changes=[]
    # Compare the entire original manifest read-only; enumerate new delivered files.
    for relative,record in baseline.items():
        p=ROOT/relative
        actual=sha(p) if p.is_file() else ''
        if actual!=record['sha256']:changes.append({'path':relative,'change':'modified' if actual else 'deleted','old_sha256':record['sha256'],'new_sha256':actual,'purpose':'P1 full coverage / validation / delivery compatibility'})
    for p in sorted(source|evidence):
        rel=p.relative_to(ROOT).as_posix()
        if rel not in baseline:changes.append({'path':rel,'change':'added','old_sha256':'','new_sha256':hashes[p],'purpose':'repair source, tests, reproducibility or acceptance evidence'})
    for r in duplicate:
        if r['path'] not in baseline:changes.append({'path':r['path'],'change':'added','old_sha256':'','new_sha256':r['sha256'],'purpose':'acceptance evidence; byte-identical copy restored by cross-package map'})
    change_data=csv_bytes(changes,['path','change','old_sha256','new_sha256','purpose'])
    (out/'CHANGE_MANIFEST.csv').write_bytes(change_data)
    index=read(ROOT/'EVIDENCE_INDEX.json')
    extras={'CHANGE_MANIFEST.csv':change_data,'OMITTED_LARGE_FILES.csv':(out/'OMITTED_LARGE_FILES.csv').read_bytes(),
            'DUPLICATE_FILE_MAP.csv':duplicate_data,'EVIDENCE_INDEX.json':(ROOT/'EVIDENCE_INDEX.json').read_bytes()}
    sums=[];packages=[]
    for label,paths in [('SOURCE',source),('ACCEPTANCE_EVIDENCE',evidence)]:
        target=out/f'URSS_REPAIR_{label}_{stamp}.zip';manifest=[]
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
            for path in sorted(paths):
                rel=path.relative_to(ROOT).as_posix()
                if rel in extras:continue
                z.write(path,rel);manifest.append({'path':rel,'size_bytes':path.stat().st_size,'sha256':hashes[path]})
            for rel,data in sorted(extras.items()):
                z.writestr(rel,data);manifest.append({'path':rel,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            z.writestr('FILE_MANIFEST.csv',csv_bytes(sorted(manifest,key=lambda r:r['path']),['path','size_bytes','sha256']))
        digest=sha(target);sums.append(f'{digest}  {target.name}');packages.append({'path':str(target),'size_bytes':target.stat().st_size,'sha256':digest,'manifest_files':len(manifest)})
    (out/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='ascii')
    (out/'PACKAGE_BUILD.json').write_text(json.dumps({'packages':packages,'session':args.session,'deduplicated_files':len(duplicate),'omitted_large_files':omitted,'built_utc':datetime.now(timezone.utc).isoformat()},indent=2)+'\n',encoding='utf-8')
    print(json.dumps(packages,indent=2))
if __name__=='__main__':main()
