#!/bin/bash
# usage: rerun.sh tag leaddir packerdir [no_think]
set -u
cd /tmp/cv
T=$1; LD=$2; PD=$3; NT=${4:-}
R='~/.caravan/bench-2026-10-31/v3.1-rerun'
M=$(basename "$PD")
echo "=== $T $(date +%T)"
python3 rc.py 2 run "mkdir -p $R && cd ~/cv3 && nohup ~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role packer --split-listen 169.254.104.38:5560 --model $PD --cache-dir $R/cache-packer-$T > $R/packer-$T.log 2>&1 < /dev/null & for i in \$(seq 1 120); do grep -q 'listening on' $R/packer-$T.log && break; grep -q -i -E 'error|Traceback' $R/packer-$T.log && break; sleep 1; done; tail -3 $R/packer-$T.log"
python3 rc.py 1 run "mkdir -p $R && cd ~/dev/caravan-v3 && nohup ~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role lead --split-peer 169.254.104.38:5560 --model $LD --port 8194 --cache-dir $R/cache-lead-$T > $R/lead-$T.log 2>&1 < /dev/null & for i in \$(seq 1 180); do grep -q 'listening on http' $R/lead-$T.log && break; grep -q -i -E 'Traceback' $R/lead-$T.log && break; sleep 1; done; tail -4 $R/lead-$T.log"
python3 rc.py 1 run "cd ~/dev/caravan-v3/bench/v3 && /opt/homebrew/bin/python3 split_client.py bench http://127.0.0.1:8194 $M $R/$T.json $NT > $R/$T.client.out 2>&1; tail -3 $R/$T.client.out; curl -s http://127.0.0.1:8194/caravan/split > $R/$T.split-after-bench.json; cat $R/$T.split-after-bench.json; echo; pkill -f 'mlx_worker.py --split-role lead'; sleep 3; tail -2 $R/lead-$T.log"
python3 rc.py 2 run "pkill -f 'mlx_worker.py --split-role packer'; sleep 3; tail -2 $R/packer-$T.log; pgrep -fl mlx_worker"
echo "=== done $T $(date +%T)"
