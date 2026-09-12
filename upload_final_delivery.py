"""Import an audited Git bundle, publish preserved history, and verify remote bytes.

Uses Git's existing authentication. It never force-pushes, deletes refs, resets a
working tree, or reruns experiments. Re-running resumes the same delivery commit.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

EXPECTED_REMOTE = 'https://github.com/rrocy6/urss-selective-locality-reduction.git'
ALLOWED_REMOTES = {EXPECTED_REMOTE, EXPECTED_REMOTE.removesuffix('.git'),
                   'git@github.com:rrocy6/urss-selective-locality-reduction.git',
                   'ssh://git@github.com/rrocy6/urss-selective-locality-reduction.git'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command, check=True, timeout=900, label=None):
    if label:
        print(label, flush=True)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', GIT_TERMINAL_PROMPT='0')
    process = subprocess.Popen([str(x) for x in command], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)
    elapsed = 0
    while True:
        try:
            stdout, stderr = process.communicate(timeout=20)
            break
        except subprocess.TimeoutExpired:
            elapsed += 20
            print((label or 'Command') + f': still running ({elapsed}s)', flush=True)
            if elapsed >= timeout:
                process.kill()
                process.communicate()
                raise RuntimeError((label or 'Command') + ' timed out; rerun the same launcher to resume.')
    result = subprocess.CompletedProcess(command, process.returncode,
                                         stdout.decode('utf-8', errors='replace'),
                                         stderr.decode('utf-8', errors='replace'))
    if check and result.returncode:
        print(result.stdout + result.stderr, flush=True)
        raise RuntimeError((label or 'Command') + ' failed with exit code ' + str(result.returncode))
    return result


def git(repo, *args, **kwargs):
    return run(['git', '-C', str(repo), *args], **kwargs)


def ancestor(repo, older, newer):
    result = git(repo, 'merge-base', '--is-ancestor', older, newer, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError('Cannot establish commit ancestry: ' + result.stderr)
    return result.returncode == 0


def remote_refs(repo):
    output = git(repo, 'ls-remote', '--symref', 'origin', 'HEAD', 'refs/heads/*', 'refs/tags/*',
                 label='READ REMOTE REFS').stdout
    refs, default = {}, None
    for line in output.splitlines():
        if line.startswith('ref: ') and line.endswith('\tHEAD'):
            default = line.split()[1]
        match = re.fullmatch(r'([0-9a-f]{40})\s+(refs/(?:heads|tags)/[^\s]+)', line)
        if match:
            refs[match[2]] = match[1]
    if default is None:
        raise RuntimeError('Remote default branch could not be established.')
    return default, refs


def publish_refs(repo, meta, session):
    commit = meta['delivery_commit']
    branch = 'refs/heads/' + meta['delivery_branch']
    default, before = remote_refs(repo)
    if default != 'refs/heads/' + meta['default_branch']:
        raise RuntimeError('The remote default branch changed; review before updating it.')
    save_json(session / 'REMOTE_BRANCHES_BEFORE.json', {'default': default, 'refs': before})
    # Fetch refs before ancestry decisions; a concurrent later update is still
    # protected by ordinary non-forced push rejection.
    git(repo, 'fetch', '--no-tags', 'origin', default, label='FETCH DEFAULT BRANCH')
    if branch in before:
        git(repo, 'fetch', '--no-tags', 'origin', branch, label='FETCH DELIVERY BRANCH')
    refspecs = []
    if branch not in before or ancestor(repo, before[branch], commit):
        refspecs.append(commit + ':' + branch)
    elif not ancestor(repo, commit, before[branch]):
        raise RuntimeError('The delivery branch has diverged. Its existing history was preserved.')
    for name, oid in meta['preserve_tags'].items():
        ref = 'refs/tags/' + name
        if ref in before and before[ref] != oid:
            raise RuntimeError('Existing archive tag has a different commit: ' + name)
        if ref not in before:
            refspecs.append(oid + ':' + ref)
    main_status = 'MERGE_REVIEW_REQUIRED'
    update_main = ancestor(repo, before[default], commit)
    if update_main:
        refspecs.append(commit + ':' + default)
        main_status = 'FAST_FORWARD_REQUESTED'
    elif ancestor(repo, commit, before[default]):
        main_status = 'ALREADY_CONTAINS_DELIVERY'
    if refspecs:
        result = git(repo, 'push', '--atomic', 'origin', *refspecs,
                     check=False, label='PUSH CODE, RESULTS AND ARCHIVE TAGS')
        if result.returncode:
            print(result.stdout + result.stderr, flush=True)
            fallback = [r for r in refspecs if not r.endswith(':' + default)]
            if not update_main or not fallback:
                raise RuntimeError('Push did not complete. Keep the Git error and rerun the same launcher.')
            print('Default-branch update was rejected; publishing the delivery branch and tags for review.', flush=True)
            git(repo, 'push', '--atomic', 'origin', *fallback, label='PUSH REVIEW BRANCH AND TAGS')
            main_status = 'MERGE_REVIEW_REQUIRED'
    after_default, after = remote_refs(repo)
    if after_default != default or branch not in after:
        raise RuntimeError('Remote branch verification failed.')
    if after[branch] != commit:
        git(repo, 'fetch', '--no-tags', 'origin', branch, label='REFRESH DELIVERY BRANCH')
        if not ancestor(repo, commit, after[branch]):
            raise RuntimeError('The remote delivery branch no longer contains this delivery.')
    for name, oid in meta['preserve_tags'].items():
        if after.get('refs/tags/' + name) != oid:
            raise RuntimeError('Remote archive tag verification failed: ' + name)
    if after[default] == commit:
        main_status = 'PASS'
    elif main_status == 'FAST_FORWARD_REQUESTED':
        # Account for a collaborator advancing main after our successful push.
        git(repo, 'fetch', '--no-tags', 'origin', default, label='REFRESH DEFAULT BRANCH')
        main_status = 'ALREADY_CONTAINS_DELIVERY' if ancestor(repo, commit, after[default]) else 'MERGE_REVIEW_REQUIRED'
    save_json(session / 'REMOTE_BRANCHES_AFTER.json', {'default': default, 'refs': after})
    return main_status, after


def remote_content_verification(repo, remote_url, meta, session):
    verification = session / 'remote_verification.git'
    if not verification.exists():
        run(['git', 'init', '--bare', str(verification)], label='PREPARE INDEPENDENT REMOTE VERIFICATION')
    # This repository receives its objects over the remote transport, not from
    # the local bundle or a local object store.
    git(verification, 'fetch', '--depth=1', '--no-tags', remote_url,
        'refs/heads/' + meta['delivery_branch'], label='FETCH UPLOADED DELIVERY FOR VERIFICATION')
    commit = meta['delivery_commit']
    if git(verification, 'cat-file', '-e', commit + '^{commit}', check=False).returncode:
        git(verification, 'fetch', '--depth=1', '--no-tags', remote_url, commit,
            label='FETCH PRESERVED DELIVERY COMMIT')
    results = []
    for item in meta['remote_files']:
        process = subprocess.Popen(['git', '-C', str(verification), 'show', commit + ':' + item['path']],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        digest, size = hashlib.sha256(), 0
        while chunk := process.stdout.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        process.stdout.close()
        error = process.stderr.read()
        process.stderr.close()
        code = process.wait()
        if code or size != item['size_bytes'] or digest.hexdigest() != item['sha256']:
            raise RuntimeError('Remote file verification failed: ' + item['path'] + ' ' + error.decode('utf-8', errors='replace'))
        results.append(dict(item, remote_bytes_verified=True))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--resource-state', type=Path, default=Path.home() / 'Downloads/URSS_E2_E5_LOCAL_20260913_020357_715_9f6107/RESOURCE_RUN_STATE.json')
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--session', type=Path)
    args = parser.parse_args()
    kit = args.kit.resolve()
    meta = read_json(kit / 'FINAL_DELIVERY.json')
    bundle = kit / 'FINAL_DELIVERY.bundle'
    if sha(bundle) != meta['bundle_sha256']:
        raise RuntimeError('The delivery bundle differs from its recorded SHA256.')
    if args.repo:
        repo = args.repo.resolve()
    else:
        state = read_json(args.resource_state)
        if state.get('schema') != 'urss_local_resources_e5_v4' or state.get('completed') is not True:
            raise RuntimeError('A completed E2/E5 local-run state is required.')
        repo = Path(state['source_repo']).resolve()
    remote_url = git(repo, 'remote', 'get-url', '--push', 'origin').stdout.strip()
    fetch_url = git(repo, 'remote', 'get-url', 'origin').stdout.strip()
    if remote_url not in ALLOWED_REMOTES or fetch_url not in ALLOWED_REMOTES:
        raise RuntimeError('Origin must identify the expected rrocy6/urss-selective-locality-reduction repository.')
    session = args.session or Path.home() / ('Downloads/URSS_GITHUB_UPLOAD_' + meta['delivery_commit'][:12])
    session = session.resolve()
    session.mkdir(parents=True, exist_ok=True)
    state_path = session / 'UPLOAD_STATE.json'
    current = read_json(state_path) if state_path.exists() else {}
    if current and (current['delivery_commit'] != meta['delivery_commit'] or current['repo'] != str(repo)):
        raise RuntimeError('Resume session identifies different code or a different repository.')
    current.update(delivery_commit=meta['delivery_commit'], repo=str(repo), session=str(session))
    save_json(state_path, current)
    print('UPLOAD STATE: ' + str(state_path), flush=True)
    git(repo, 'cat-file', '-e', meta['bundle_base_commit'] + '^{commit}', label='CHECK PREVIOUS CODE COMMIT')
    git(repo, 'bundle', 'verify', str(bundle), label='VERIFY DELIVERY BUNDLE')
    git(repo, 'fetch', str(bundle), meta['bundle_ref'], label='IMPORT FINAL DELIVERY COMMIT')
    if git(repo, 'rev-parse', '--is-shallow-repository').stdout.strip() == 'true':
        git(repo, 'fetch', '--unshallow', 'origin', label='COMPLETE COMMIT HISTORY')
    worktree = session / 'review_worktree'
    if not worktree.exists():
        git(repo, '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'worktree', 'add', '--detach',
            str(worktree), meta['delivery_commit'], label='PREPARE ISOLATED REVIEW WORKTREE')
    if git(worktree, 'rev-parse', 'HEAD').stdout.strip() != meta['delivery_commit']:
        raise RuntimeError('Review worktree commit changed.')
    if git(worktree, 'status', '--porcelain', '--untracked-files=normal').stdout.strip():
        raise RuntimeError('Review worktree contains local edits; preserve them before resuming.')
    local_audit = session / 'LOCAL_DELIVERY_VERIFICATION.json'
    run([sys.executable, '-X', 'utf8', '-u', worktree / 'verify_final_delivery.py',
         '--repo', worktree, '--json-output', local_audit], label='VERIFY ALL ORIGINAL EXPERIMENT ARCHIVES')
    if read_json(local_audit)['status'] != 'PASS':
        raise RuntimeError('Local delivery verification did not pass.')
    main_status, refs = publish_refs(repo, meta, session)
    verified = remote_content_verification(repo, remote_url, meta, session)
    receipt = dict(status='PASS', delivery_commit=meta['delivery_commit'],
                   delivery_branch=meta['delivery_branch'], default_branch_status=main_status,
                   remote_refs=refs, remote_files_verified=verified,
                   verified_at_utc=datetime.now(timezone.utc).isoformat(),
                   original_branch_deletions=0, force_pushes=0, experiments_rerun=0)
    save_json(session / 'UPLOAD_RECEIPT.json', receipt)
    current.update(completed=True, default_branch_status=main_status, receipt=str(session / 'UPLOAD_RECEIPT.json'))
    save_json(state_path, current)
    print('ALL LOCAL RESULTS UPLOADED + REMOTE VERIFY: PASS', flush=True)
    print('MAIN: ' + main_status, flush=True)
    print('DELIVERY COMMIT: ' + meta['delivery_commit'], flush=True)
    print('VERIFIED REMOTE FILES: ' + str(len(verified)), flush=True)
    print('RECEIPT: ' + str(session / 'UPLOAD_RECEIPT.json'), flush=True)
    print('BRANCH: https://github.com/rrocy6/urss-selective-locality-reduction/tree/' + meta['delivery_branch'], flush=True)
    if main_status == 'MERGE_REVIEW_REQUIRED':
        print('MAIN requires a reviewed merge; all delivery files are verified on the delivery branch.', flush=True)
        print('COMPARE: https://github.com/rrocy6/urss-selective-locality-reduction/compare/' + meta['default_branch'] + '...' + meta['delivery_branch'] + '?expand=1', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('UPLOAD STOPPED: ' + str(exc), file=sys.stderr, flush=True)
        print('Keep the original error. Rerun the same launcher to resume; successful remote writes are not undone.', file=sys.stderr, flush=True)
        sys.exit(1)
