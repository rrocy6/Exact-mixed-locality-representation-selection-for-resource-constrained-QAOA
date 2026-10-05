"""Report compiler resource differences without altering frozen audit criteria."""
from pathlib import Path
from datetime import datetime, timezone
import importlib.util
import importlib.metadata
import json
import platform
import sys

root = Path.cwd()
study_root = root/'archives/feedback_iteration_v3'
if not (study_root/'audit.py').is_file():
    raise SystemExit('Run this script from the restored repository root.')
sys.path.insert(0, str(study_root))
import audit
s = audit.s
s.validate_freeze()
out = root/'verification'/('v3_resource_diagnosis_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
out.mkdir(parents=True)
report = {'purpose':'diagnosis only; does not replace or relax the original strict audit',
          'platform':platform.platform(), 'python':sys.version,
          'packages':{p:importlib.metadata.version(p) for p in ['qiskit','numpy','scipy','matplotlib','PyYAML','pypdf']},
          'freeze_sha256':s.io.sha(study_root/'freeze.json'), 'circuits':[], 'errors':[]}
for path in sorted((study_root/'execution/results').glob('*.json')):
    r = s.io.read(path)
    if r['number'] != 0:
        continue
    ins, poly, seed, rejected = s.generate(r['family'],r['number'])
    for domain, cid in r['capacity_selection'].items():
        if cid is None:
            continue
        item = {'instance':r['id'], 'domain':domain, 'candidate_id':cid}
        try:
            row = r['rows'][cid]
            rep = s.representation(poly,r['n'],row['actions'])
            fidelity, actual = audit.circuit_check(poly,rep,row['probabilities'])
            expected = row['resources']
            item.update(state_fidelity=fidelity, expected=expected, actual=actual,
                differences={k:{'expected':expected.get(k),'actual':actual.get(k)}
                for k in sorted(set(expected)|set(actual)) if expected.get(k)!=actual.get(k)})
            print(json.dumps({k:v for k,v in item.items() if k in ['instance','domain','state_fidelity','differences']},ensure_ascii=True),flush=True)
        except Exception as exc:
            item['error'] = repr(exc)
            report['errors'].append({'instance':r['id'],'domain':domain,'error':repr(exc)})
        report['circuits'].append(item)
        (out/'diagnosis.json').write_text(json.dumps(report,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
s.validate_freeze()
fields = sorted({k for c in report['circuits'] for k in c.get('differences',{})})
report.update(circuits_checked=len(report['circuits']),differing_fields=fields,
              strict_resource_match=not fields and not report['errors'],
              diagnosis_completed=len(report['circuits'])==9 and not report['errors'])
(out/'diagnosis.json').write_text(json.dumps(report,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
print('CIRCUITS_CHECKED:',len(report['circuits']))
print('DIFFERING_FIELDS:',fields)
print('STRICT_RESOURCE_MATCH:',report['strict_resource_match'])
print('DIAGNOSIS_FILE:',str(out/'diagnosis.json'))
sys.exit(1 if report['errors'] else 0)
