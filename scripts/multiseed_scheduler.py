"""Killable task processes. Deadline starts immediately before Process.start()."""
import multiprocessing as mp
import time
import os
import uuid
from datetime import datetime, timezone

def _child(connection, run, task, seed, trials, attempt):
    try:
        try:
            from scripts.multiseed_experiment import compile_batch_worker
        except ModuleNotFoundError:
            from multiseed_experiment import compile_batch_worker
        observation_id = str(uuid.uuid4())
        started_utc = datetime.now(timezone.utc).isoformat()
        result = compile_batch_worker((str(run), [task], seed, trials, attempt))
        for row in result['rows']:
            row.update(observation_id=observation_id, worker_pid=os.getpid(), worker_started_utc=started_utc)
        connection.send(result)
    except BaseException as exc:
        connection.send({'worker_error': f'{type(exc).__name__}: {exc}'})
    finally:
        connection.close()

def execute_batches(run, batches, workers, timeout, target=None):
    if workers < 1 or timeout <= 0:
        raise ValueError('Positive worker count and timeout required')
    ctx = mp.get_context('spawn')
    jobs = iter((bid, task, seed, trials, attempt) for bid, tasks, seed, trials, attempt in batches for task in tasks)
    expected = {b[0]: len(b[1]) for b in batches}
    completed = {b[0]: [] for b in batches}
    active = []
    exhausted = False
    try:
        while active or not exhausted:
            while len(active) < workers and not exhausted:
                job = next(jobs, None)
                if job is None:
                    exhausted = True
                    break
                bid, task, seed, trials, attempt = job
                receive, send = ctx.Pipe(duplex=False)
                proc = ctx.Process(target=target or _child, args=(send, run, task, seed, trials, attempt))
                started = time.monotonic()
                proc.start()
                send.close()
                active.append((proc, receive, started, job))
            for entry in active[:]:
                proc, receive, started, job = entry
                bid, task, seed, trials, attempt = job
                elapsed = time.monotonic() - started
                result = None
                status = None
                if elapsed >= timeout:
                    status = 'timeout'
                elif receive.poll():
                    try:
                        result = receive.recv()
                    except EOFError:
                        status = 'compile_error'
                elif not proc.is_alive():
                    status = 'compile_error'
                else:
                    continue
                if proc.is_alive():
                    proc.terminate()
                proc.join(timeout=2)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=2)
                receive.close()
                active.remove(entry)
                if result is None or 'worker_error' in result:
                    error = (result or {}).get('worker_error', 'Task deadline exceeded' if status == 'timeout' else 'Worker exited without result')
                    rows = [{**{k: task[k] for k in ('task_id','instance_id','candidate_id','topology','synthesis','seed')},
                             'status': status or 'compile_error', 'attempt_id': attempt, 'resources_json': '',
                             'error': error, 'elapsed_seconds': elapsed, 'circuit_sha256': '', 'circuit_path': ''}]
                else:
                    rows = result['rows']
                completed[bid].extend(rows)
                if len(completed[bid]) == expected[bid]:
                    yield bid, {'status': 'pass' if all(r['status'] in {'compiled','width_exceeded'} for r in completed[bid]) else 'error',
                                'seed': seed, 'attempt_id': attempt, 'rows': completed.pop(bid)}
            if active:
                time.sleep(0.01)
    finally:
        for proc, connection, _, _ in active:
            if proc.is_alive():
                proc.terminate()
            proc.join(timeout=2)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=2)
            connection.close()
