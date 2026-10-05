"""Restore two P1 evidence files only when drift is purely CRLF conversion."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone

root = Path.cwd()
commit = 'ec2456a04ee4d26c12298f7d305a568e6aa3f3e2'
relative = Path('corrections/review_v2_20260920/p1_full_20260920T232002Z')
report = json.loads((root/relative/'P1_REPORT.json').read_text(encoding='utf-8-sig'))
expected = {'INPUT_COPY_MANIFEST.json': report['identity']['inputs_manifest_hash'],
            'p1_repetition_rows.csv': report['rows_sha256']}
changes = []
for name, digest in expected.items():
    path = relative/name
    original = subprocess.check_output(['git', 'show', commit+':'+path.as_posix()])
    current = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != digest:
        raise RuntimeError('Committed bytes do not match frozen report: '+name)
    if current.replace(b'\r\n', b'\n') != original.replace(b'\r\n', b'\n'):
        raise RuntimeError('Non-newline changes detected; refusing overwrite: '+name)
    changes.append((path, current, original))
out = root/'verification'/('windows_p1_fix_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
out.mkdir(parents=True)
for path, current, original in changes:
    (out/(path.name+'.before')).write_bytes(current)
    path.write_bytes(original)
attrs = root/'.gitattributes'
rule = '/'+relative.as_posix()+'/** -text'
if rule not in attrs.read_text(encoding='utf-8').splitlines():
    with attrs.open('ab') as f:
        f.write(('\n# Preserve all frozen P1 evidence bytes on Windows.\n'+rule+'\n').encode())
(out/'repair.json').write_text(json.dumps({'status':'PASS','source_commit':commit,'files':list(expected),'scope':'only newline differences restored; expected hashes unchanged'},indent=2))
print('P1_CHECKOUT_REPAIR: PASS', flush=True)
failed = []
for study in ['p1', 'compiled', 'qaoa', 'v3']:
    print('VERIFYING: '+study, flush=True)
    with (out/(study+'.log')).open('wb') as log:
        result = subprocess.run([sys.executable, '-X', 'utf8', 'scripts/reproduce_restored_archives.py', study, '--output', str(out/study)],stdout=log,stderr=subprocess.STDOUT)
    print((out/(study+'.log')).read_text(encoding='utf-8',errors='replace')[-2500:],flush=True)
    if result.returncode:
        failed.append(study)
        break
print('LOG_DIRECTORY: '+str(out))
print('REMAINING_VERIFICATION: '+('FAIL '+','.join(failed) if failed else 'PASS'))
sys.exit(bool(failed))
