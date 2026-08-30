#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, statistics
from pathlib import Path
from challenge_common import load_yaml, sequence_by_seed

def fmt(seconds):
    if seconds is None: return "unknown"
    seconds=int(max(0,seconds)); return f"{seconds//3600:02d}:{seconds%3600//60:02d}:{seconds%60:02d}"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--protocol",required=True); ap.add_argument("--output-root",required=True); ap.add_argument("--pid-file")
    a=ap.parse_args(); seeds=sorted(sequence_by_seed(load_yaml(Path(a.protocol)))); root=Path(a.output_root)
    done=[]; runtimes=[]
    for seed in seeds:
        p=root/f"trajectory_{seed}"/"summary.json"
        if p.is_file():
            o=json.loads(p.read_text()); done.append(seed); runtimes.append(float(o.get("runtime_seconds",0)))
    running=False; pid=None
    if a.pid_file and Path(a.pid_file).is_file():
        try:
            pid=int(Path(a.pid_file).read_text().strip()); Path(f"/proc/{pid}").exists() and None; running=Path(f"/proc/{pid}").exists()
        except Exception: pass
    med=statistics.median(runtimes) if runtimes else None; rem=(len(seeds)-len(done))*med if med else None
    print("V2.1 ACTIVATION/CARRYOVER PROGRESS")
    print("checked:",dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    print(f"process: {'RUNNING' if running else 'UNKNOWN_OR_FINISHED'}"+(f" pid={pid}" if pid else ""))
    print(f"completed: {len(done)}/{len(seeds)} ({100*len(done)/len(seeds):.1f}%)")
    print("median_completed_trajectory:",fmt(med)); print("estimated_remaining:",fmt(rem))
    pending=[s for s in seeds if s not in done]; print("next_pending:",pending[0] if pending else "none")
    return 0
if __name__=="__main__": raise SystemExit(main())
