"""Build and verify the delivered-source paper artifact map without rewriting history."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = 'corrections/review_v2_20260920/PAPER_ARTIFACT_MAP.json'
NEW = 'corrections/review_v2_20260920/closeout_20260921T130854186Z_0458abb8/PAPER_ARTIFACT_MAP_v2.json'

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def build(root=ROOT):
    old = json.loads((root / OLD).read_text(encoding='utf-8'))
    paths = {item['path'] for item in old['artifacts'] + old['implementation_files']}
    paths.update([OLD, 'paper/main.tex', 'scripts/multiseed_p1.py',
                  'scripts/check_p1_coverage.py', 'scripts/multiseed_scheduler.py',
                  'scripts/multiseed_compile.py', 'scripts/multiseed_validation.py',
                  'scripts/multiseed_experiment.py', 'scripts/verify_multiseed_correction.py'])
    for directory in ('results/multiseed_20260918T163717Z',
                      'corrections/review_v2_20260920/final_analysis',
                      'corrections/review_v2_20260920/p1_full_20260920T232002Z'):
        paths.update(p.relative_to(root).as_posix() for p in (root / directory).rglob('*')
                     if p.is_file() and p.stat().st_size <= 50 * 1024**2)
    bindings = []
    for rel in sorted(paths):
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(rel)
        bindings.append({'path': rel, 'sha256': digest(path), 'size_bytes': path.stat().st_size})
    return {'schema': 'URSS_PAPER_ARTIFACT_MAP_V2', 'version': 2,
            'generated_utc': datetime.now(timezone.utc).isoformat(),
            'historical_analysis_identity': {'map_path': OLD, 'map_sha256': digest(root / OLD),
                                             'implementation_files': old['implementation_files'],
                                             'analysis_run': old['analysis_run']},
            'delivered_source_identity': {'note': 'Current delivered bytes; historical analyses were not rerun with these files',
                                          'bindings': bindings},
            'excluded_regenerable_large_tables': 'See OMITTED_LARGE_FILES.csv in delivery'}

def verify(root=ROOT, map_path=NEW):
    data = json.loads((root / map_path).read_text(encoding='utf-8'))
    assert data['schema'] == 'URSS_PAPER_ARTIFACT_MAP_V2'
    historical = data['historical_analysis_identity']
    assert digest(root / historical['map_path']) == historical['map_sha256']
    for item in data['delivered_source_identity']['bindings']:
        path = root / item['path']
        assert path.is_file() and path.stat().st_size == item['size_bytes'] and digest(path) == item['sha256'], item['path']
    return len(data['delivered_source_identity']['bindings'])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--verify', action='store_true'); args = parser.parse_args()
    if args.verify:
        print(json.dumps({'status': 'pass', 'verified_bindings': verify()}))
    else:
        target = ROOT / NEW
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(target)
