"""Copy the installed, read-only revision into a new multiseed evidence root."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'revisions/URSS_20260917_verified_v1'


def main():
    run = ROOT / 'results' / ('multiseed_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    run.mkdir(parents=True, exist_ok=False)
    inputs = run / 'inputs'
    inputs.mkdir()
    active = SOURCE / 'fix_v2/active'
    paths = {
        'experiments': active / 'revision/experiments',
        'paper_original': active / 'revision/overleaf',
        'requirements-revision.txt': active / 'requirements-revision.txt',
        'PATCH_PROVENANCE.json': active / 'PATCH_PROVENANCE.json',
        'README_FIX_V2.md': SOURCE / 'fix_v2/README_FIX_V2.md',
        'VERIFICATION_REPORT_v2.md': SOURCE / 'fix_v2/VERIFICATION_REPORT_v2.md',
        'task.md': ROOT / 'URSS_CODEX_TASK_MULTISEED.md',
    }
    records = []
    for name, source in paths.items():
        target = inputs / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(source, target)
        for p in sorted(target.rglob('*')) if target.is_dir() else [target]:
            if p.is_file():
                records.append({'path': p.relative_to(run).as_posix(), 'source': str(source / p.relative_to(target) if target.is_dir() else source), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    (run / 'INPUT_COPY_MANIFEST.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    (run / 'initial_worktree.patch').write_bytes(subprocess.check_output(['git', 'diff', '--binary'], cwd=ROOT))
    status = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT)
    (run / 'initial_git_status.txt').write_bytes(status)
    # A file outside the immutable run makes the exact path easy to recover.
    (ROOT / 'scripts/multiseed_latest_run.txt').write_text(str(run), encoding='utf-8')
    print(run, flush=True)


if __name__ == '__main__':
    main()
