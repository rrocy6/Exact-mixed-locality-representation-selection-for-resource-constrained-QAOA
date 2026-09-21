"""Validate actual ZIPs by safe re-extraction, hashes and relative-path execution."""
import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
from datetime import datetime, timezone
import zipfile
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.assemble_acceptance import assemble

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def unpack(path,target):
    if target.exists():raise ValueError('New extraction directory required')
    target.mkdir(parents=True)
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate ZIP member')
        for name in names:
            q=PurePosixPath(name)
            if q.is_absolute() or '..' in q.parts or '\\' in name or ':' in name:raise ValueError('Unsafe ZIP path')
            if (z.getinfo(name).external_attr>>16)&0o170000==0o120000:raise ValueError('Symlink ZIP entry')
        if z.testzip() is not None:raise ValueError('ZIP CRC failure')
        z.extractall(target)
    with (target/'FILE_MANIFEST.csv').open(encoding='utf-8',newline='') as f:manifest=list(csv.DictReader(f))
    if set(names)!={r['path'] for r in manifest}|{'FILE_MANIFEST.csv'}:raise ValueError('Manifest coverage failure')
    for r in manifest:
        p=target/r['path']
        if p.stat().st_size!=int(r['size_bytes']) or sha(p)!=r['sha256']:raise ValueError('Extracted hash mismatch: '+r['path'])
    return {'zip_integrity':'pass','path_safety':'pass','file_hashes':'pass','verified_files':len(manifest),'sha256':sha(path),'size_bytes':path.stat().st_size}

def main():
    p=argparse.ArgumentParser();p.add_argument('--delivery',type=Path,required=True);a=p.parse_args();out=a.delivery.resolve()
    root=out/'extracted_validation';root.mkdir(exist_ok=False)
    builds=json.loads((out/'PACKAGE_BUILD.json').read_text(encoding='utf-8'))['packages'];checks=[];commands=[]
    report={'status':'running','packages':checks,'commands':commands}
    try:
        expected={line.split('  ',1)[1]:line.split('  ',1)[0] for line in (out/'SHA256SUMS.txt').read_text().splitlines()}
        for item,label in zip(builds,('source','evidence')):
            path=out/Path(item['path']).name
            assert sha(path)==expected[path.name]==item['sha256']
            checks.append({'name':path.name,**unpack(path,root/label)})
        assembled=root/'assembled';report['assembly']=assemble(root/'source',root/'evidence',assembled)
        session_name=json.loads((out/'PACKAGE_BUILD.json').read_text(encoding='utf-8'))['session']
        session=json.loads((assembled/session_name).read_text(encoding='utf-8-sig'))
        required=['scripts/multiseed_experiment.py','scripts/multiseed_p1.py','scripts/multiseed_scheduler.py','scripts/check_p1_coverage.py',
                  'tests/test_p1_full_coverage.py','P1_COVERAGE_AND_PACKAGING_REPORT.md','EVIDENCE_INDEX.json','BASE_FILE_MANIFEST.csv',session['full_run']+'/requirements-p1-lock.txt']
        for relative in required:assert (assembled/relative).is_file(),relative
        report['required_files']='pass'
        commands_to_run=[['-m','unittest','discover','-s','tests','-v'],
            ['golden_example/run_tests.py'],
            ['scripts/check_p1_coverage.py','--source','results/multiseed_20260918T163717Z','--run',session['full_run'],'--strict',
             '--output',str(root/'EXTRACTED_P1_COVERAGE.json'),'--csv',str(root/'extracted_p1_coverage.csv')],
            ['scripts/verify_multiseed_correction.py','--source','results/multiseed_20260918T163717Z','--corrected','corrections/review_v2_20260920/final_analysis','--output',str(root/'EXTRACTED_NUMERICAL.json')],
            ['scripts/build_paper_artifact_map_v2.py','--verify'],
            ['-c',"from pathlib import Path; from scripts import multiseed_experiment as m; from scripts.multiseed_p1 import require_full_gate; import json; s=json.loads(Path('P1_PACKAGING_SESSION.json').read_text()); r=Path(s['full_run']); c,ss,cc,_=m.load_run(r); require_full_gate(m,r,c,ss,cc); old=m.load_run(Path('corrections/review_v2_20260920/final_analysis')); print('Full P1 gate and saved-run relative dependencies: PASS')"]]
        # Windows tempfile users can exceed MAX_PATH under the deep extraction tree.
        temporary=out.parents[4]/'r12tmp'/out.name
        temporary.mkdir(parents=True,exist_ok=False)
        environment=os.environ.copy()
        environment.update({'TMP':str(temporary),'TEMP':str(temporary),'TMPDIR':str(temporary)})
        environment.pop('PYTHONPATH',None)
        for i,args in enumerate(commands_to_run):
            argv=[sys.executable,'-X','utf8','-B',*args];start=time.monotonic()
            log=root/f'entry_{i}.log'
            started=datetime.now(timezone.utc).isoformat()
            with log.open('w',encoding='utf-8') as f:result=subprocess.run(argv,cwd=assembled,env=environment,stdout=f,stderr=subprocess.STDOUT)
            commands.append({'argv':argv,'cwd':str(assembled),'started_utc':started,'python':sys.executable,'temporary_directory':str(temporary),'pythonpath_removed':True,'exit_code':result.returncode,'duration_seconds':time.monotonic()-start,'log':log.relative_to(out).as_posix()})
            if result.returncode:raise RuntimeError('Extracted entry failed: '+str(args))
        test_log=(root/'entry_0.log').read_text(encoding='utf-8')
        count=re.search(r'Ran (\d+) tests?',test_log)
        required_tests=('test_bundle_covers_all_frozen_tiers','test_compilation_design_injection_has_eight_designs',
                        'test_qaoa_design_injection_has_eight_feasible_designs','test_selector_validation_conversion_preserves_all_rows',
                        'test_v2_test_bundle_uses_dynamic_active_auxiliary_count')
        bundle={name:bool(re.search(r'^'+name+r' .* \.\.\. ok$',test_log,re.M)) for name in required_tests}
        skipped=len(re.findall(r'^test_.*\.\.\. skipped ',test_log,re.M))
        report['unittest']={'count':int(count.group(1)) if count else 0,'skipped':skipped,'five_bundle_tests':bundle}
        if report['unittest']['count']<193 or skipped or not all(bundle.values()):
            raise RuntimeError('Full test coverage or frozen bundle check failed')
        report.update(status='pass',dependency_resolution='pass; both packages only; no base archive needed for these checks',entry_validation='pass',
                      extracted_p1_report='extracted_validation/EXTRACTED_P1_COVERAGE.json',
                      limitations=['existing Python dependencies reused; clean install not validated','regenerable large budget CSVs intentionally not materialized'])
    except Exception as exc:
        report.update(status='fail',error=f'{type(exc).__name__}: {exc}')
    (out/'PACKAGE_VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(main())
