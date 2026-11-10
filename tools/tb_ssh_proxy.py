#!/usr/bin/env python3
"""SSH ProxyCommand run on a hop Mini: rediscover peer TB IPv4 every connection.

Usage on the hop: python3 tools/tb_ssh_proxy.py user@peer-control en2 22
Control SSH is used only for interface discovery; nc carries the actual SSH
stream over the newly resolved Thunderbolt address. Never caches an IP or
changes host-key checking. Any configured peer/interface/port is supported.
"""
import argparse,os,sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"agent"))
from service_endpoints import resolve

def discover(endpoint):
    # The parent SSH protocol is already arriving on stdin. Discovery's own SSH
    # must not consume any of it before nc takes over the byte stream.
    def run(*args,**kwargs):
        return subprocess.run(*args,stdin=subprocess.DEVNULL,**kwargs)
    return resolve(endpoint,run=run)


def main(argv=None,*,resolve_fn=discover,exec_fn=os.execvp):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("peer");ap.add_argument("interface");ap.add_argument("port",type=int)
    ap.add_argument("--show-address",action="store_true")
    args=ap.parse_args(argv)
    endpoint=resolve_fn(f"ssh+tb://{args.peer}/{args.interface}:{args.port}")
    host,port=endpoint.rsplit(":",1)
    if args.show_address:print(endpoint);return 0
    exec_fn("/usr/bin/nc",["nc",host,port])
    return 0
if __name__=="__main__":
    try:raise SystemExit(main())
    except (ValueError,RuntimeError,OSError) as e:
        print("Thunderbolt SSH discovery failed: "+str(e),file=sys.stderr);raise SystemExit(1)
