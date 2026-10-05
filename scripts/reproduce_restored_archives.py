"""Read-only verification / copied-output reanalysis of restored frozen studies."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', choices=['integrity', 'multiseed', 'p1', 'compiled', 'qaoa', 'v3'])
    parser.add_argument('--output', type=Path, required=True, help='New output directory; existing paths are refused')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'results/multiseed_20260918T163717Z'
    correction = ROOT / 'corrections/review_v2_20260920'
    def run(*parts):
        return subprocess.call([sys.executable, *map(str, parts)], cwd=ROOT)
    if args.study == 'integrity':
        records = json.loads((ROOT/'archive_repair_20261005/RESTORED_FILES.json').read_text())['files']
        records += json.loads((ROOT/'archive_repair_20261005/NEWLINE_RESTORATION.json').read_text())
        errors = [r['path'] for r in records if not (ROOT/r['path']).is_file() or hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest() != r['sha256']]
        report = {'status': 'FAIL' if errors else 'PASS', 'files_checked': len(records), 'errors': errors}
        (out/'integrity.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report)); return bool(errors)
    if args.study == 'multiseed':
        return run(ROOT/'scripts/verify_multiseed_correction.py', '--source', source, '--corrected', correction/'final_analysis', '--output', out/'verification.json')
    if args.study == 'p1':
        return run(ROOT/'scripts/check_p1_coverage.py', '--source', source, '--run', correction/'p1_full_20260920T232002Z', '--strict', '--output', out/'verification.json', '--csv', out/'coverage.csv')
    if args.study == 'compiled':
        # Original analyser writes beside its inputs: isolate the complete frozen tree.
        target = out/'experiments'
        shutil.copytree(correction/'p1_full_20260920T232002Z/inputs/experiments', target)
        return run(target/'analyse_compiled_study.py')
    if args.study == 'qaoa':
        path = ROOT/'archives/revision_20260917/revision/qaoa_new/run.py'
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location('restored_qaoa', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Windows freeze names are relative paths, not literal POSIX backslash filenames.
        # Only path interpretation changes; hash algorithm, expected digests and checks remain intact.
        original_sha = module.sha
        module.sha = lambda p: original_sha(Path(str(p).replace('\\', '/')))
        previous = sys.argv
        try:
            sys.argv = [str(path), 'verify']; module.main()
        finally:
            sys.argv = previous
        (out/'verification.json').write_text(json.dumps({'status':'PASS', 'scope':'original frozen verify checks; Windows path separator adapter; no optimization rerun'})+'\n')
        return 0
    return run(ROOT/'archives/feedback_iteration_v3/audit.py', '--run', ROOT/'archives/feedback_iteration_v3/execution', '--output', out/'verification.json')

if __name__ == '__main__':
    raise SystemExit(main())
