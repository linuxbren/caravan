S='bash ~/.caravan/bench-2026-11-04/v19/scripts'
for V in v2.1 v2 v1; do echo "== $V llama write $(date +%T)"; ssh exo1 "$S/single.sh $V llama write"; done
echo ALL_W_DONE $(date +%T)
