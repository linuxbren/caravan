# Day 20 expanded benchmark evidence

Result interpretation and full tables: `../../../docs/DAY20.md`, `matrix.md`, `matrix.csv`.

`raw/` includes failed controls for honesty; only the explicit matrix.csv source
rows form the successful baseline. Stream events include reasoning for the
synthetic public task, not the private system/tool instructions.

`bin/matrix.py`, `probe.py`, `control.py`, orchestration and optional aux service
trial helper are the actual Omarchy scripts. They default to its local18190 /
18090 tunnels and its `~/day20-speedups/{private,raw}` tree. They are operational
lab helpers, not a generic load-test service. Do not run overlapping model
switches; always verify the final target and restore Huihui after trials.
`control.py` treats an explicitly requested guarded single-placement denial as
an observed result; inspect the saved HTTP response, not just the exit status.

Run `capture-prefix.py` with Hermes's venv Python from the desired working
directory for a NEW offline dataset. It imports installed Hermes inspection
APIs, preserving all tools. It writes potentially private instructions under
private/ (700, files600). NEVER commit private/. Use retained frozen bodies for
exact reproduction; regenerated system context/tool versions may differ.

The checked-in service trial helper describes this lab's optional EXO1 sidecar.
Production generic launcher is `tools/aux_worker.py`; its normal default budget
is2GB. The .9GB setting was explicitly measured for local Qwen2.5-0.5B only.
No Hermes config is changed, no model downloads, no sudo. Disable routing by
removing CARAVAN_AUX_MODEL from the proxy's environment and reloading only that
idle job; stop only com.caravan.v3.aux if no longer needed. Main model and caches
are separate. Use repo paths EXO1~/dev/caravan-v3, EXO2~/cv3 only.
