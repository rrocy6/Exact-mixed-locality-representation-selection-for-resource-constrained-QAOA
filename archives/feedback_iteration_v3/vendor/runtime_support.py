"""I/O and provenance fixes; no change to the frozen numerical algorithm."""
from __future__ import annotations
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import sys
import tempfile


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(root, name):
    parts=PurePosixPath(str(name).replace('\\','/'))
    require(not parts.is_absolute() and '..' not in parts.parts and ':' not in str(parts), 'Unsafe relative path')
    path=root.joinpath(*parts.parts)
    require(path.resolve().is_relative_to(root.resolve()),'Path leaves its root')
    return path


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')
    descriptor,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def atomic_grid(path, grid):
    import numpy as np
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            np.savez_compressed(stream,objective=grid);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def archive_root(active):
    active=Path(active).resolve()
    near=active.parent/'payload'
    return near if near.is_dir() else active.parent.parent/'payload'


def verify_active(active):
    require(not sys.flags.optimize,'Python -O disables historical assertions; use normal Python for verification')
    active=Path(active).resolve();record=read(active/'PATCH_PROVENANCE.json')
    require(record['schema']=='urss-operational-fix-v2','Unexpected provenance schema')
    archive=archive_root(active)
    require(sha(archive/'MANIFEST_SHA256.json')==record['base_manifest_sha256'],'Wrong archival baseline')
    for name,digest in read(archive/'MANIFEST_SHA256.json').items():
        require(sha(relative(archive,name))==digest,'Archived input changed: '+name)
    for name,digest in record['active_files'].items():
        require(sha(relative(active,name))==digest,'Active file changed: '+name)
    # Verify the original experiment hashes against their preserved original files.
    for name,digest in read(archive/'revision/qaoa_new/freeze.json')['hashes'].items():
        require(sha(relative(archive/'revision',name))==digest,'Original QAOA freeze mismatch: '+name)
    return record


def runtime_environment():
    import numpy as np
    capture=io.StringIO()
    with redirect_stdout(capture):np.show_config()
    packages={name:importlib.metadata.version(name) for name in ['numpy','scipy','qiskit','matplotlib','PyYAML','pypdf']}
    return {'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),
            'packages':packages,'numpy_configuration':capture.getvalue(),
            'thread_environment':{k:os.environ.get(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','RAYON_NUM_THREADS','NPY_DISABLE_CPU_FEATURES']}}


def enforce_versions(active):
    require(sys.version_info[:2]==(3,12),'This delivery requires Python 3.12')
    for line in (Path(active)/'requirements-revision.txt').read_text().splitlines():
        if '==' not in line:continue
        name,version=line.strip().split('==')
        require(importlib.metadata.version(name)==version,'Wrong pinned dependency: '+line)


def descriptor(active, study, selection):
    active=Path(active)
    return {'schema':'urss-replay-v2','study':study,'selection':selection,
            'active_provenance_sha256':sha(active/'PATCH_PROVENANCE.json'),
            'protocol_sha256':sha(active/'revision/qaoa_new/protocol.json'),
            'environment':runtime_environment(),
            'interpretation':'Replay of frozen inputs; no new confirmatory cohort and no overwrite of archival results'}


@contextmanager
def exclusive_lock(path):
    # The OS releases this lock on exit, including a killed process. Keep the
    # inode: unlinking a locked file creates a race with waiting processes.
    stream=open(path,'a+b')
    acquired=False
    try:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        acquired=True
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        stream.close()


@contextmanager
def run_directory(output, active, descriptor_value, resume=False):
    output=Path(output).resolve();active=Path(active).resolve()
    require(not output.is_relative_to(active) and not output.is_relative_to(archive_root(active).resolve()), 'Replay output must be outside active and payload')
    if output.exists():
        require(resume,'Output already exists; use --resume for a matching replay')
        context=read(output/'RUN_CONTEXT.json')
        require(context['descriptor']==descriptor_value,'Resume rejected: code, input, scope or runtime environment changed')
    else:
        require(not resume,'Cannot resume: output directory does not exist')
        output.mkdir(parents=True)
        context={'descriptor':descriptor_value,'started_utc':utc(),'status':'PREPARED'}
        atomic_json(output/'RUN_CONTEXT.json',context)
    lock=output/'RUNNING.lock'
    with exclusive_lock(lock):
        # Reload after taking the lock; another process may have just finished.
        context=read(output/'RUN_CONTEXT.json')
        require(context['descriptor']==descriptor_value,'Run context changed while acquiring lock')
        try:
            context.update(status='RUNNING',last_started_utc=utc());atomic_json(output/'RUN_CONTEXT.json',context)
            yield output
        except BaseException as exc:
            context.update(status='INTERRUPTED',error=f'{type(exc).__name__}: {exc}')
            atomic_json(output/'RUN_CONTEXT.json',context)
            raise
        else:
            context.update(status='COMPLETED',completed_utc=utc());context.pop('error',None)
            atomic_json(output/'RUN_CONTEXT.json',context)


def valid_completed(output, stem):
    marker=output/'completed'/(stem+'.json')
    if not marker.exists():return False
    record=read(marker)
    require(record['run_descriptor_sha256']==hashlib.sha256(json.dumps(read(output/'RUN_CONTEXT.json')['descriptor'],sort_keys=True).encode()).hexdigest(), 'Completion belongs to another run')
    result=read(output/'results'/(stem+'.json'))
    grids=[row['grid_file'] for row in result['rows'] if 'grid_file' in row]
    expected={f'results/{stem}.json',f'instances/{stem}.json',*grids}
    require(len(grids)==3 and set(record['files'])==expected,'Incomplete completion manifest: '+stem)
    for name,digest in record['files'].items():
        require(sha(relative(output,name))==digest,'Completed result was changed or is incomplete: '+name)
    return True


def commit_result(output, stem, names):
    value={'run_descriptor_sha256':hashlib.sha256(json.dumps(read(output/'RUN_CONTEXT.json')['descriptor'],sort_keys=True).encode()).hexdigest(),
           'files':{name:sha(relative(output,name)) for name in names}}
    atomic_json(output/'completed'/(stem+'.json'),value)
