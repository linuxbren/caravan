#!/usr/bin/env python3
"""Private per-account browser handoff. Capability never appears in process args."""
import argparse
import json
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'proxy'))
from pairing_store import Store,atomic,read_json


def launch_file(port=8190,*,home=None,next_home=False):
    store=Store(home=home)
    with store.locked():
        path=store.root/'control.json';control=read_json(path)
        if control is None:
            control={'capability':secrets.token_hex(32)};atomic(path,json.dumps(control),backup=False)
        token=control['capability']
        if len(token)!=64 or any(c not in '0123456789abcdef' for c in token): raise ValueError('Invalid local browser permission; keep the file for review.')
        target=f'http://127.0.0.1:{int(port)}/pairing#pair={token}'+('&next=home' if next_home else '')
        # A private HTML handoff avoids exposing the capability in `ps`/open args
        # or HTTP access logs. The pairing page erases the fragment immediately.
        page=store.root/('open-home.html' if next_home else 'open-pairing.html')
        atomic(page,'<!doctype html><meta charset="utf-8"><title>Opening Caravan</title><script>location.replace('+json.dumps(target)+');</script><p>Opening Caravan in your browser…</p>',backup=False)
        return page


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','launch-file'))
    p.add_argument('--port',type=int,default=8190);p.add_argument('--home-page',action='store_true');args=p.parse_args(argv)
    if not 1<=args.port<=65535:p.error('invalid web address')
    store=Store()
    if args.action=='prepare':
        # Installer-only: prepare the first short-lived offer, never renew a used
        # or exhausted one on update. Renewal is an explicit local UI action.
        with store.locked(): fresh=not (store.root/'offer.json').exists()
        if fresh:
            from pairing import prepare_offer,display_code
            offer=prepare_offer(store)
            print('To add this Mac: on your first Mac choose Add Macs, then enter '+display_code(offer)+'.')
            print('Keep this one-use code private. It expires in five minutes. Open Add Macs on this Mac to show a new one.')
        else: print('To connect Macs, open Add Macs in Caravan. Existing connections are unchanged.')
    else: print(launch_file(args.port,next_home=args.home_page))
    return 0


if __name__=='__main__':sys.exit(main())
