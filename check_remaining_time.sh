python - "$P" "$O/delta_grid" <<'PY'
from pathlib import Path
from datetime import timedelta
import sys
import yaml

protocol = yaml.safe_load(Path(sys.argv[1]).read_text())
root = Path(sys.argv[2])

seeds = protocol["delta_calibration"]["trajectory_specs"]
grid = protocol["delta_calibration"]["delta_grid"]
total = len(seeds) * len(grid)

completed = list(
    root.glob("trajectory_*/delta_*/delta_harm_events.csv")
)
done = len(completed)
remaining = total - done

print(f"Kész:       {done}/{total} ({100 * done / total:.2f}%)")
print(f"Hátra:      {remaining}/{total} ({100 * remaining / total:.2f}%)")

times = sorted(path.stat().st_mtime for path in completed)

if len(times) >= 2:
    window = times[-min(30, len(times)):]
    average = (window[-1] - window[0]) / (len(window) - 1)
    eta_seconds = average * remaining

    print(f"Átlag:      {average / 60:.2f} perc/futás")
    print(f"Durva ETA:  {timedelta(seconds=int(eta_seconds))}")
else:
    print("ETA-hoz még nincs elég befejezett futás.")
PY
