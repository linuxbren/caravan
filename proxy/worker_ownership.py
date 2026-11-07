"""Fail-closed termination of a tracked UI worker; never process-name sweeps."""
from __future__ import annotations
import argparse
import json
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path


def option(argv, name):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv): return argv[i+1]
        if a.startswith(name + "="): return a.split("=",1)[1]
    return None


def matches(command, worker, *, port=None, listen=None):
    try: args=shlex.split(command)
    except ValueError: return False
    if len(args)<2 or not Path(args[0]).name.lower().startswith("python"):
        return False
    # Require the exact repository script, not a substring in a shell command.
    expected=Path(worker).expanduser().resolve()
    scripts=[a for a in args[1:] if Path(a).name=="mlx_worker.py"]
    if not any(Path(a).expanduser().resolve()==expected for a in scripts): return False
    if listen is not None:
        return option(args,"--split-role") in ("front","packer") and option(args,"--split-listen")==listen
    return port is not None and option(args,"--port")==str(port)


def command_of(pid):
    try: return subprocess.check_output(["ps","-o","command=","-p",str(pid)],text=True).strip()
    except subprocess.CalledProcessError: return ""


def stop(worker, *, pid=None, pid_file=None, port=None, listen=None,
         inspect=command_of, send=os.kill, pause=time.sleep, timeout=8):
    if pid is None and pid_file:
        try: pid=int(Path(pid_file).expanduser().read_text().strip())
        except (OSError,ValueError): return {"stopped":False,"reason":"no tracked pid"}
    if not pid or int(pid)<=1: return {"stopped":False,"reason":"invalid tracked pid"}
    pid=int(pid)
    def owned():return matches(inspect(pid),worker,port=port,listen=listen)
    if not owned(): return {"stopped":False,"reason":"pid absent or identity mismatch","pid":pid}
    try:send(pid,signal.SIGTERM)
    except ProcessLookupError:return {"stopped":False,"reason":"already exited","pid":pid}
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline and owned():pause(0.05)
    if owned():
        # Recheck before escalation: PID reuse must never kill another process.
        try:send(pid,signal.SIGKILL)
        except ProcessLookupError:pass
    return {"stopped":True,"pid":pid}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--worker",required=True);p.add_argument("--pid",type=int)
    p.add_argument("--pid-file");p.add_argument("--port",type=int);p.add_argument("--listen")
    a=p.parse_args();print(json.dumps(stop(a.worker,pid=a.pid,pid_file=a.pid_file,port=a.port,listen=a.listen)))
if __name__=="__main__":main()
