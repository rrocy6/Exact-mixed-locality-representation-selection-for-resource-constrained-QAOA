"""Run the mixer repair gate; never launch experiments or overwrite evidence."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import traceback
import unittest
from datetime import datetime, timezone
from pathlib import Path

from urss_pipeline.e4_warmstart import MIXER_CONVENTION, require_uniform_null_control


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--full-suite', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output_dir or root / 'evidence' / ('mixer_null_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    if not output.is_absolute():
        output = Path.cwd() / output
    output.mkdir(parents=True, exist_ok=False)
    modules = ['tests.test_mixer_null_control', 'tests.test_e4_warmstart',
               'tests.test_e3_qaoa', 'tests.test_four_part_addendum_v1',
               'tests.test_fibre_postprocess_v2', 'tests.test_fibre_rerun']
    result = None
    preflight = {'status': 'not_run'}
    with (output / 'TEST_OUTPUT.txt').open('x', encoding='utf-8', newline='\n') as log:
        tee = Tee(sys.stdout, log)
        with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
            try:
                preflight = require_uniform_null_control()
                print(json.dumps(preflight, indent=2))
                suite = (unittest.defaultTestLoader.discover(str(root / 'tests'), top_level_dir=str(root))
                         if args.full_suite else unittest.defaultTestLoader.loadTestsFromNames(modules))
                result = unittest.TextTestRunner(verbosity=2, stream=tee).run(suite)
            except Exception as error:
                preflight = {'status': 'fail', 'error': str(error)}
                traceback.print_exc()
    try:
        commit = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    packages = {}
    for name in ('numpy', 'scipy', 'qiskit', 'qiskit-aer', 'PyYAML', 'jsonschema', 'reportlab'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = 'not_installed'
    sources = sorted(root.glob('urss_pipeline/*.py')) + sorted(root.glob('tests/test_*.py')) + [Path(__file__).resolve()]
    audit = {
        'schema_version': 'mixer_null_control_audit_v1',
        'status': 'pass' if preflight['status'] == 'pass' and result and result.wasSuccessful() and not result.skipped else 'fail',
        'mixer_convention': MIXER_CONVENTION, 'preflight': preflight,
        'tests_run': result.testsRun if result else 0,
        'failures': len(result.failures) if result else None,
        'errors': len(result.errors) if result else None,
        'skipped': len(result.skipped) if result else None,
        'test_scope': 'full_pipeline_suite' if args.full_suite else modules,
        'git_head': commit, 'git_dirty': dirty,
        'python': sys.version, 'platform': platform.platform(), 'packages': packages,
        'command_argv': sys.argv,
        'source_sha256': {str(path.relative_to(root)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        'test_log_sha256': hashlib.sha256((output / 'TEST_OUTPUT.txt').read_bytes()).hexdigest(),
        'targeted_480_row_rerun_performed': False, 'full_e4_rerun_performed': False,
        'manuscript_modified': False,
        'meaning': 'Implementation regression gate only; not evidence of a positive scientific effect.',
    }
    (output / 'NULL_CONTROL_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
    print(f"MIXER NULL CONTROL: {audit['status'].upper()} — {output}")
    return 0 if audit['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
