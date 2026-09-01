# V2.1 activation and cross-drift carryover challenge

This frozen add-on challenges mechanisms that V2 calibration/confirmation did not
exercise sufficiently. It does not recalibrate `W` or `delta_W`, does not pool with
V2, and must not be described as deployment-prevalence validation.

## Frozen design

- 18 new trajectory seeds, disjoint from V1/V2.
- All six permutations of `touch`, `broken`, and `combo`, three trajectories each.
- `clean` before, between, and after non-clean blocks.
- 15 proposal + 15 gate + 60 evaluation samples per block.
- A forced label-free update opportunity on every non-clean block.
- Frozen `W`, `delta_W=12`, identity-volume radius, gate thresholds, margins, and engine.
- Full 27-state counterfactual projection/gate stress in the actual entering B3 context.
- Carryover endpoint: target evaluation before the target's own update.
- Technical PASS means provenance/completeness only; adverse harm is a valid result.

## Outputs per trajectory

- `controller_events.csv`
- `window_results.csv`
- `carryover_events.csv`
- `projection_gate_stress.csv`
- `partition_map.json`
- `summary.json`

The aggregate audit is `challenge_audit.json`. Freeze only after it reports
`technical_ok: true` and 18/18 trajectories.

See `RUNBOOK_NODE01.md` for exact commands.
