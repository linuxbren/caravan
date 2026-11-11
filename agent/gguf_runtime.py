"""Pinned GGUF own-share backend; isolated first-use build, never production patching."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
PIN='76a67730ffc7d650dffa4db04d96be84a59e7ef3'
MARKER='catalog-v1/'+PIN


def current():
    configured=os.environ.get('CARAVAN_GGUF_SHARD_BIN')
    candidates=[Path(configured).expanduser()] if configured else [Path.home()/'.caravan/runtimes/gguf-shards'/PIN/'build/bin',Path.home()/'.caravan/day22-runtime/build/bin']
    for b in candidates:
        marker=b.parents[1]/'caravan-shards-version'
        if marker.is_file() and marker.read_text().strip()==MARKER and all((b/n).is_file() for n in ('llama-server','ggml-rpc-server')):return b
    raise FileNotFoundError('Own-part GGUF backend is not installed; first GGUF download builds the pinned backend on each Mac')


def ensure():
    try:return current()
    except FileNotFoundError:
        if os.environ.get('CARAVAN_GGUF_SHARD_BIN'):raise
    base=Path.home()/'.caravan/runtimes/gguf-shards';base.mkdir(parents=True,exist_ok=True)
    lock=base/'build.lock'
    if lock.is_symlink():raise ValueError('linked runtime lock refused')
    with lock.open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        try:return current()
        except FileNotFoundError:pass
        src=base/'source.git';dst=base/PIN
        if any(p.is_symlink() for p in (base,src,dst)):raise ValueError('linked runtime folder refused')
        if not dst.exists():
            if not src.exists():subprocess.run(['git','init','--bare',str(src)],check=True)
            subprocess.run(['git','-C',str(src),'fetch','--depth=1','https://github.com/ggml-org/llama.cpp.git',PIN],check=True)
            script=Path(__file__).resolve().parents[1]/'runtime/gguf-shards/apply.py'
            subprocess.run([sys.executable,str(script),str(src),str(dst)],check=True)
        marker=dst/'caravan-shards-version'
        if not marker.is_file() or marker.read_text().strip()!=MARKER:raise ValueError('incomplete isolated runtime; retained for inspection, not patched twice')
        print('Preparing own-part GGUF backend on this Mac (no model weights cross the cable)',flush=True)
        subprocess.run(['cmake','-S',str(dst),'-B',str(dst/'build'),'-DGGML_RPC=ON','-DLLAMA_CURL=OFF','-DLLAMA_BUILD_TESTS=OFF'],check=True)
        subprocess.run(['cmake','--build',str(dst/'build'),'-j','4','--target','llama-server','ggml-rpc-server'],check=True)
        return current()
