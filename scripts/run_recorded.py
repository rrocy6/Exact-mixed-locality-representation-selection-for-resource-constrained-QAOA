"""Run a command, preserving UTF-8 stdout/stderr, argv, duration and exit code."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import time
def main():
    p=argparse.ArgumentParser();p.add_argument('--record',type=Path,required=True);p.add_argument('--cwd',type=Path,default=Path.cwd());p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args();command=a.command[1:] if a.command[:1]==['--'] else a.command
    a.record.parent.mkdir(parents=True,exist_ok=True)
    if a.record.exists():raise ValueError('Command record already exists')
    start=datetime.now(timezone.utc).isoformat();clock=time.monotonic()
    with a.record.with_suffix('.log').open('w',encoding='utf-8') as f:result=subprocess.run(command,cwd=a.cwd,stdout=f,stderr=subprocess.STDOUT)
    a.record.write_text(json.dumps({'argv':command,'cwd':str(a.cwd.resolve()),'started_utc':start,'duration_seconds':time.monotonic()-clock,'exit_code':result.returncode,'log':a.record.with_suffix('.log').name},indent=2)+'\n',encoding='utf-8')
    return result.returncode
if __name__=='__main__':raise SystemExit(main())
