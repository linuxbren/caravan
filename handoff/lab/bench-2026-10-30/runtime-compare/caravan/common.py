"""Shared prompt builders (identical needle/filler text to suite-1 smoke.py) + memory sampler."""
import json, os, subprocess, threading, time, statistics
CITIES = ["Lisbon","Oslo","Kyoto","Denver","Nairobi","Lima","Perth","Tallinn","Quebec","Hanoi","Porto","Bergen"]
ITEMS = ["copper wire","glass jars","oak planks","wool blankets","steel bolts","rice sacks","tea chests","solar panels"]
def filler(n, off=0):
    lines = []
    for i in range(off, off + n):
        c = CITIES[(i * 7) % len(CITIES)]; it = ITEMS[(i * 5) % len(ITEMS)]
        lines.append(f"Record {i+1}: the {c} depot logged {(i * 37) % 900 + 100} units of {it} on day {(i % 28) + 1}.")
    return lines
NEEDLE = "Important note: the vault access code is ORCHID-7419."
Q = ("Answer in one short line each, no explanation. 1) What is the vault access code? "
     "2) What is 17 multiplied by 23? 3) What is the capital of Australia?")
def prompts():
    lines = filler(290); lines.insert(60, NEEDLE)
    return {"short": NEEDLE + "\n" + Q, "long": "Here is a long inventory log.\n" + "\n".join(lines) + "\n\n" + Q}
def score(text):
    t = (text or "")
    return {"code": "ORCHID-7419" in t, "mult": "391" in t, "capital": "Canberra" in t}
def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None

class MemSampler:
    """Every `iv` s: system free % (memory_pressure), swap used, and summed RSS + phys_footprint of matching procs."""
    def __init__(self, path, pattern, iv=2.0):
        self.path, self.pattern, self.iv = path, pattern, iv
        self.peak_rss = 0; self.peak_fp = 0; self.min_free = 100; self.stop_ev = threading.Event()
    def sample(self):
        pids = subprocess.run(["pgrep", "-f", self.pattern], capture_output=True, text=True).stdout.split()
        rss = 0; fp = 0
        for p in pids:
            r = subprocess.run(["ps", "-o", "rss=", "-p", p], capture_output=True, text=True).stdout.strip()
            rss += int(r) * 1024 if r.isdigit() else 0
            f = subprocess.run(["footprint", "-p", p, "-f", "bytes", "--noCategories"], capture_output=True, text=True).stdout
            for line in f.splitlines():
                if line.strip().startswith("phys_footprint:"):
                    try: fp += int(line.split(":")[1].split()[0])
                    except Exception: pass
                    break
        mp = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout.strip().splitlines()[-1]
        free = int(mp.split(":")[1].strip().rstrip("%")) if ":" in mp else 100
        sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
        self.peak_rss = max(self.peak_rss, rss); self.peak_fp = max(self.peak_fp, fp); self.min_free = min(self.min_free, free)
        return f"{time.strftime('%T')} pids={','.join(pids)} rss={rss/1e9:.2f}GB fp={fp/1e9:.2f}GB free={free}% swap[{sw}]"
    def run(self):
        with open(self.path, "a") as f:
            while not self.stop_ev.is_set():
                try: f.write(self.sample() + "\n"); f.flush()
                except Exception as e: f.write(f"err {e}\n")
                self.stop_ev.wait(self.iv)
    def __enter__(self):
        self.t = threading.Thread(target=self.run, daemon=True); self.t.start(); return self
    def __exit__(self, *a):
        self.stop_ev.set(); self.t.join(10)
    def summary(self):
        return {"peak_rss_gb": round(self.peak_rss / 1e9, 2), "peak_footprint_gb": round(self.peak_fp / 1e9, 2), "min_free_pct": self.min_free}
