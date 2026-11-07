#!/bin/bash
set -u
RC="python3 /workspace/rc.py"
R='~/.caravan/bench-2026-10-31/idea1-pipeline'
PEER=169.254.104.38:5560
PY='~/.caravan/venvs/mlx/bin/python'
LD_BASE='~/.exo/models'
PD_BASE='~/.caravan/mlx-models'

stop_workers() {
  $RC 1 run "pkill -f 'mlx_worker.py --split-role lead' || true; sleep 2; true"
  $RC 2 run "pkill -f 'mlx_worker.py --split-role packer' || true; sleep 2; true"
}

start_pair() {
  local TAG=$1 MD=$2 K=$3 PIPE=$4
  local LD="$LD_BASE/$MD"
  local PD="$PD_BASE/$MD"
  local KFLAG=""
  if [ "$K" != "even" ]; then KFLAG="--split-packer-layers $K"; fi
  local PFLAG=""
  if [ "$PIPE" != "1" ]; then PFLAG="--split-pipeline-chats $PIPE"; fi
  echo "=== start $TAG K=$K pipe=$PIPE $(date +%T)"
  $RC 2 run "mkdir -p $R && cd ~/cv3 && nohup $PY agent/mlx_worker.py --split-role packer --split-listen $PEER --model $PD --cache-dir $R/cache-packer-$TAG $KFLAG --no-persist > $R/packer-$TAG.log 2>&1 < /dev/null & for i in \$(seq 1 120); do grep -q 'listening on' $R/packer-$TAG.log && break; grep -qi Traceback $R/packer-$TAG.log && break; sleep 1; done; tail -4 $R/packer-$TAG.log"
  $RC 1 run "mkdir -p $R && cd ~/dev/caravan-v3 && nohup $PY agent/mlx_worker.py --split-role lead --split-peer $PEER --model $LD --port 8194 --cache-dir $R/cache-lead-$TAG --prompt-cache-size 8 $KFLAG $PFLAG --no-persist > $R/lead-$TAG.log 2>&1 < /dev/null & for i in \$(seq 1 180); do grep -q 'listening on http' $R/lead-$TAG.log && break; grep -qi Traceback $R/lead-$TAG.log && break; sleep 1; done; tail -5 $R/lead-$TAG.log"
}

run_baseline() {
  local TAG=$1 MD=$2 NT=${3:-}
  local M=$(basename "$MD")
  echo "=== baseline $TAG $(date +%T)"
  $RC 1 run "cd ~/dev/caravan-v3/bench/v3 && /opt/homebrew/bin/python3 split_client.py bench http://127.0.0.1:8194 $M $R/$TAG.json $NT > $R/$TAG.client.out 2>&1; rg -n 'tg128|quality_score|write_tps' $R/$TAG.client.out | head -20; tail -5 $R/$TAG.client.out"
}

run_pipe() {
  local TAG=$1 MD=$2 N=$3 NT=${4:-}
  local M=$(basename "$MD")
  echo "=== pipe N=$N $TAG $(date +%T)"
  $RC 1 run "cd ~/dev/caravan-v3/bench/v3 && /opt/homebrew/bin/python3 pipeline_bench.py http://127.0.0.1:8194 $M $R/$TAG-n$N.json $N $NT > $R/$TAG-n$N.client.out 2>&1; tail -25 $R/$TAG-n$N.client.out"
}

stop_workers

# Baselines flag-off even cut
start_pair gemma-base-off mlx-community--gemma-4-26b-a4b-it-4bit even 1
run_baseline gemma-base-off mlx-community--gemma-4-26b-a4b-it-4bit
stop_workers

start_pair gptoss-base-off mlx-community--gpt-oss-20b-MXFP4-Q8 even 1
run_baseline gptoss-base-off mlx-community--gpt-oss-20b-MXFP4-Q8
stop_workers

start_pair qwen-base-off mlx-community--Qwen3-30B-A3B-4bit even 1
run_baseline qwen-base-off mlx-community--Qwen3-30B-A3B-4bit no_think
stop_workers

echo "=== BASELINES DONE $(date +%T)"

# Idea 1 with idea-5 cuts: for each model, start pipe=3 once, run N=1,2,3
# Gemma K=16
start_pair gemma-pipe mlx-community--gemma-4-26b-a4b-it-4bit 16 3
run_pipe gemma-pipe mlx-community--gemma-4-26b-a4b-it-4bit 1
run_pipe gemma-pipe mlx-community--gemma-4-26b-a4b-it-4bit 2
run_pipe gemma-pipe mlx-community--gemma-4-26b-a4b-it-4bit 3
stop_workers

# GPT-OSS K=13
start_pair gptoss-pipe mlx-community--gpt-oss-20b-MXFP4-Q8 13 3
run_pipe gptoss-pipe mlx-community--gpt-oss-20b-MXFP4-Q8 1
run_pipe gptoss-pipe mlx-community--gpt-oss-20b-MXFP4-Q8 2
run_pipe gptoss-pipe mlx-community--gpt-oss-20b-MXFP4-Q8 3
stop_workers

# Qwen K=24 even
start_pair qwen-pipe mlx-community--Qwen3-30B-A3B-4bit 24 3
run_pipe qwen-pipe mlx-community--Qwen3-30B-A3B-4bit 1 no_think
run_pipe qwen-pipe mlx-community--Qwen3-30B-A3B-4bit 2 no_think
run_pipe qwen-pipe mlx-community--Qwen3-30B-A3B-4bit 3 no_think
stop_workers

$RC 1 run "pgrep -fl mlx_worker || echo no_worker; lsof -iTCP:8194 -sTCP:LISTEN 2>/dev/null || echo 8194_free"
$RC 2 run "pgrep -fl mlx_worker || echo no_worker; lsof -iTCP:5560 -sTCP:LISTEN 2>/dev/null || echo 5560_free"
echo "=== ALL DONE $(date +%T)"
