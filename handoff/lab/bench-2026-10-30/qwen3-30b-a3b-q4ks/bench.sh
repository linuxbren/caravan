#!/bin/zsh
# usage: bench.sh <tag> <model.gguf>
set -u
TAG=$1; M=$2
B=~/.caravan/bench-2026-10-30/$TAG; mkdir -p $B
LB=~/dev/llama.cpp/build/bin/llama-bench
snap() { echo "== $1 $(date +%T)"; sysctl vm.swapusage; memory_pressure | tail -1; vm_stat | egrep "free|active|wired|compressor"; }
run() { # name, args...
  local n=$1; shift
  echo ">>> $n $(date +%T): $*" | tee -a $B/progress.log
  snap "before $n" >> $B/mem.log
  ( while true; do echo "$(date +%T) $(sysctl -n vm.swapusage) $(memory_pressure | tail -1)"; sleep 5; done ) > $B/mem-$n.log 2>&1 &
  local sp=$!
  /usr/bin/time -l $LB -m $M -ngl 999 -o json "$@" > $B/$n.json 2> $B/$n.err
  local rc=$?
  kill $sp 2>/dev/null
  snap "after $n" >> $B/mem.log
  echo "<<< $n rc=$rc $(date +%T) maxrss=$(grep 'maximum resident' $B/$n.err | awk '{print $1}') peakfp=$(grep 'peak memory footprint' $B/$n.err | awk '{print $1}')" | tee -a $B/progress.log
  return $rc
}
echo "start $(date) steps=${STEPS:-all}" >> $B/progress.log
want() { [ -z "${STEPS:-}" ] || [[ " $STEPS " == *" $1 "* ]]; }
want A && { run A_fa_f16   -r 3 -p 512,4096 -n 128 -fa 0,1 -ctk f16 -ctv f16 || exit 1; }
want B && { run B_fa1_q8   -r 3 -p 512,4096 -n 128 -fa 1 -ctk q8_0 -ctv q8_0 || exit 1; }
want C && run C_ub       -r 3 -p 512,4096 -n 128 -fa 1 -ctk q8_0 -ctv q8_0 -b 2048 -ub 512,1024,2048
want C2 && run C2_ub2048_v -r 3 -p 512,4096 -n 128 -fa 1 -ctk q8_0 -ctv q8_0 -b 2048 -ub 2048 -v
want D && { run D_d8k_f16  -r 2 -p 512 -n 128 -d 8192 -fa 1 -ctk f16 -ctv f16
            run D_d8k_q8   -r 2 -p 512 -n 128 -d 8192 -fa 1 -ctk q8_0 -ctv q8_0
            run D_d16k_q8  -r 2 -p 512 -n 128 -d 16384 -fa 1 -ctk q8_0 -ctv q8_0; }
echo "done $(date)" >> $B/progress.log
