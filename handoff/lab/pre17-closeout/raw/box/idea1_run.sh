#!/bin/bash
# Idea 1 bench driver — run from box with rc.py in /workspace
set -u
RC="python3 /workspace/rc.py"
R='~/.caravan/bench-2026-10-31/idea1-pipeline'
PEER=169.254.104.38:5560
PY='~/.caravan/venvs/mlx/bin/python'
LD_BASE='~/.exo/models'
PD_BASE='~/.caravan/mlx-models'

stop_workers() {
  $RC 1 run "pkill -f 'mlx_worker.py --split-role lead' || true; sleep 2; pgrep -fl mlx_worker || echo no_lead"
  $RC 2 run "pkill -f 'mlx_worker.py --split-role packer' || true; sleep 2; pgrep -fl mlx_worker || echo no_packer"
}

start_pair() {
  # args: tag model_dirname K pipeline_n extra_lead_args
  local TAG=$1 MD=$2 K=$3 PIPE=$4
  local EXTRA=${5:-}
  local LD="$LD_BASE/$MD"
  local PD="$PD_BASE/$MD"
  local KFLAG=""
  if [ -n "$K" ] && [ "$K" != "even" ]; then
    KFLAG="--split-packer-layers $K"
  fi
  local PFLAG=""
  if [ -n "$PIPE" ] && [ "$PIPE" != "1" ]; then
    PFLAG="--split-pipeline-chats $PIPE"
  fi
  echo "=== start $TAG K=$K pipe=$PIPE $(date +%T)"
  $RC 2 run "mkdir -p $R && cd ~/cv3 && nohup $PY agent/mlx_worker.py --split-role packer --split-listen $PEER --model $PD --cache-dir $R/cache-packer-$TAG $KFLAG --no-persist > $R/packer-$TAG.log 2>&1 < /dev/null & for i in \$(seq 1 120); do grep -q 'listening on' $R/packer-$TAG.log && break; grep -qiE 'error|Traceback' $R/packer-$TAG.log && break; sleep 1; done; tail -5 $R/packer-$TAG.log"
  $RC 1 run "mkdir -p $R && cd ~/dev/caravan-v3 && nohup $PY agent/mlx_worker.py --split-role lead --split-peer $PEER --model $LD --port 8194 --cache-dir $R/cache-lead-$TAG --prompt-cache-size 8 $KFLAG $PFLAG --no-persist $EXTRA > $R/lead-$TAG.log 2>&1 < /dev/null & for i in \$(seq 1 180); do grep -q 'listening on http' $R/lead-$TAG.log && break; grep -qiE 'Traceback' $R/lead-$TAG.log && break; sleep 1; done; tail -6 $R/lead-$TAG.log"
}

run_baseline() {
  local TAG=$1 MD=$2 NT=${3:-}
  local M=$(basename "$MD")
  echo "=== baseline split_client $TAG $(date +%T)"
  $RC 1 run "cd ~/dev/caravan-v3/bench/v3 && /opt/homebrew/bin/python3 split_client.py bench http://127.0.0.1:8194 $M $R/$TAG.json $NT > $R/$TAG.client.out 2>&1; tail -20 $R/$TAG.client.out"
}

run_pipe() {
  local TAG=$1 MD=$2 N=$3 NT=${4:-}
  local M=$(basename "$MD")
  echo "=== pipeline_bench N=$N $TAG $(date +%T)"
  $RC 1 run "cd ~/dev/caravan-v3/bench/v3 && /opt/homebrew/bin/python3 pipeline_bench.py http://127.0.0.1:8194 $M $R/$TAG-n$N.json $N $NT > $R/$TAG-n$N.client.out 2>&1; tail -30 $R/$TAG-n$N.client.out"
}

# --- Gemma baseline flag-off even cut ---
stop_workers
start_pair gemma-base-off mlx-community--gemma-4-26b-a4b-it-4bit even 1
run_baseline gemma-base-off mlx-community--gemma-4-26b-a4b-it-4bit
stop_workers

# --- GPT-OSS baseline ---
start_pair gptoss-base-off mlx-community--gpt-oss-20b-MXFP4-Q8 even 1
run_baseline gptoss-base-off mlx-community--gpt-oss-20b-MXFP4-Q8
stop_workers

# --- Qwen baseline ---
start_pair qwen-base-off mlx-community--Qwen3-30B-A3B-4bit even 1
run_baseline qwen-base-off mlx-community--Qwen3-30B-A3B-4bit no_think
stop_workers

echo "=== baselines done $(date +%T)"
