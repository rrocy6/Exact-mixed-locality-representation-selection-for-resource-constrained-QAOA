import json
from datetime import datetime,timezone
from compiled_study import OUT,ROOT,CONFIG,dump,sha
freeze=json.loads((OUT/'freeze.json').read_text())
existing=sorted(p.stem for p in (OUT/'instances').glob('*.json'))
assert len(existing)==60 and not any(x.startswith('pair_star') for x in existing)
assert sha(ROOT/'compiled_study_frozen_v1.py')==freeze['source_sha256']
dump(OUT/'amendment_01.json',{
 'amended_utc':datetime.now(timezone.utc).isoformat(),
 'original_source_sha256':freeze['source_sha256'],
 'amended_source_sha256':sha(ROOT/'compiled_study.py'),
 'original_source_file':'compiled_study_frozen_v1.py',
 'original_protocol_file':'COMPILED_PROTOCOL_frozen_v1.md',
 'amended_protocol_sha256':sha(ROOT/'COMPILED_PROTOCOL.md'),
 'config':CONFIG,'completed_original_protocol_instances':existing,
 'completed_constructed_instances_before_amendment':0,
 'reason':'32-candidate assertion failed: constructed family has exactly 27 capacity-feasible full assignments; cap both spaces equally',
 'unchanged':['instance generator','instances','objective','compiler settings','budget grid','all random-family results'],
 'scope':'constructed family mechanism evaluation amended; original random-family evaluation unchanged'})
print('Recorded technical amendment before constructed-family results')
