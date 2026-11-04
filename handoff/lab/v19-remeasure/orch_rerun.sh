S='bash ~/.caravan/bench-2026-11-04/v19/scripts'
for T in qwen3 llama; do echo "== v1 $T prefix $(date +%T)"; ssh exo1 "mv ~/.caravan/bench-2026-11-04/v19/single/v1-$T-prefix ~/.caravan/bench-2026-11-04/v19/single/v1-$T-prefix-aborted-hfdownload 2>/dev/null; $S/single.sh v1 $T prefix"; done
echo ALL_RERUN_DONE $(date +%T)
