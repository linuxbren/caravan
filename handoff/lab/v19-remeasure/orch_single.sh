S='bash ~/.caravan/bench-2026-11-04/v19/scripts'
for V in v2.1 v2 v1; do echo "== $V llama write $(date +%T)"; ssh exo1 "$S/single.sh $V llama write"; done
for V in v2.1 v1; do for T in qwen3 llama; do echo "== $V $T prefix $(date +%T)"; ssh exo1 "$S/single.sh $V $T prefix"; done; done
for i in $(seq 1 120); do ssh exo1 'test -f ~/.caravan/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf' && break; sleep 10; done
echo "== v0 $(date +%T)"
ssh exo1 "$S/v0.sh write llama"; ssh exo1 "$S/v0.sh prefix qwen3"; ssh exo1 "$S/v0.sh prefix llama"
for V in v2.1 v2 v1; do echo "== rerun $V llama write $(date +%T)"; ssh exo1 "$S/single.sh $V llama write"; done
echo ALL_SINGLE_DONE $(date +%T)
