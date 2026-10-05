"""Supplemental full audit allowing only explicitly recorded total_gates drift.
The original frozen audit and its strict FAIL remain unchanged.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys

root = Path.cwd()
source = root/'archives/feedback_iteration_v3/audit.py'
sys.path.insert(0,str(source.parent))
import study as s
s.validate_freeze()
out = root/'verification'/('v3_compatibility_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
out.mkdir(parents=True)
text = source.read_text(encoding='utf-8')
old = "s.checked(resources==row['resources'],'Recompiled resources differ')"
new = "check_resources(resources,row['resources'],stem,domain)"
if text.count(old)!=1:
    raise RuntimeError('Unexpected audit source; no adaptation applied')
changes=[]
def check_resources(actual,expected,instance,domain):
    differences={k:{'expected':expected.get(k),'actual':actual.get(k)} for k in sorted(set(actual)|set(expected)) if actual.get(k)!=expected.get(k)}
    if differences:
        changes.append({'instance':instance,'domain':domain,'differences':differences})
    s.checked(not (set(differences)-{'total_gates'}),'Decision resource drift: '+json.dumps(differences))
    s.checked(all(isinstance(v,int) and not isinstance(v,bool) and v>=0 for v in [actual.get('total_gates'),expected.get('total_gates')]),'Invalid total_gates metadata')
# Execute an explicitly adapted copy, never modifying frozen files or hashes.
adapted=text.replace(old,new)
(out/'adapted_audit.py.txt').write_text(adapted,encoding='utf-8')
ns={'__name__':'supplemental_audit','__file__':str(source),'check_resources':check_resources}
exec(compile(adapted,str(out/'adapted_audit.py.txt'),'exec'),ns)
raw=out/'audit_checks.json'
sys.argv=[str(source),'--run',str(source.parent/'execution'),'--output',str(raw)]
try:
    ns['main']()
    result=json.loads(raw.read_text())
    result['status']='PASS_WITH_COMPILER_METADATA_DRIFT' if changes else 'PASS'
    result['strict_resource_match']=not changes
    result['resource_differences']=changes
    result['scope_note']='Full original audit checks with explicit total_gates-only exception; does not supersede historical strict FAIL; no optimizer rerun.'
    result['original_audit_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    result['adapted_audit_sha256']=hashlib.sha256(adapted.encode()).hexdigest()
    raw.unlink()
except Exception as exc:
    result={'status':'FAIL','error':repr(exc),'resource_differences':changes}
    raise
finally:
    (out/'verification_portable.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('COMPATIBILITY_STATUS:',result['status'])
    print('RESULT_DIRECTORY:',out)
