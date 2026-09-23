# IVC transition-entry feasibility: inventory before implementation

This research branch is **separate from the frozen V2/V2.1 evidence**. The first
question is whether naturally accepted states vary enough to justify a
state-dependent entry decision. Do not build or train an entry gate, rerun the
3,000-point grid, or start a GPU benchmark as part of this inventory.

## Inputs and output

`inventory_v21.py` reads the existing V2.1 `outputs/challenge/trajectory_*`
directories (`summary.json`, `carryover_events.csv`, `partition_map.json`) and
the neighboring `challenge_audit.json` when present. It selects **B3 only**:
other controller rows repeat the same transitions and are not independent
evidence. The program never modifies its inputs and prints JSON to stdout.

The report records naturally reached inherited states by source condition and
ordered source/target pair, target-block fingerprints, input hashes, and the
number of target blocks already seen under different inherited states. A count
of different states across *different* target blocks is only a feasibility
signal. It does **not** identify the causal effect of state or the achievable
benefit of a gate. The existing `projection_gate_stress.csv` uses deliberately
proposed states and is excluded from this natural-state inventory.

## Run on Node01

Keep the current checkout and frozen V2.1 outputs in place. Fetch this branch
into a separate worktree; substitute your actual repository path if needed:

```bash
R="$HOME/ocr-segmentation"
W="$HOME/ocr-segmentation-ivc-entry"
git -C "$R" fetch origin research/ivc-entry-feasibility
git -C "$R" worktree add -b research/ivc-entry-feasibility "$W" origin/research/ivc-entry-feasibility
```

If the worktree already exists, use `git -C "$W" pull --ff-only` instead of
`git worktree add`. First confirm that the historical per-trajectory results
are present in the original checkout:

```bash
Q="$R/mathematical_framework/recalibration_2026_v2/challenges/activation_carryover_v1"
test -f "$Q/outputs/challenge_audit.json"
test -f "$Q/outputs/challenge/trajectory_86082801/carryover_events.csv"
```

Then produce a report **outside Git**; this reads CSV/JSON and launches no
pipeline or OCR jobs:

```bash
mkdir -p "$HOME/ivc-entry-results"
python3 "$W/research/ivc_entry_feasibility/inventory_v21.py" --challenge-root "$Q/outputs/challenge" > "$HOME/ivc-entry-results/v21_state_inventory.json"
python3 -m json.tool "$HOME/ivc-entry-results/v21_state_inventory.json" > /dev/null
```

If the ignored Node01 outputs are no longer present, retrieve the frozen
`V2_1_Activation_Carryover_Challenge_2026-08-30.zip` evidence bundle from the
`bounded-adaptation-v2.1.0` release, verify its SHA-256 against
`release/bounded_adaptation_v2_1/EVIDENCE_BUNDLES.sha256`, and point
`--challenge-root` at its extracted directory containing `trajectory_*`.
Check the actual archive layout first. A release audit JSON alone cannot
reconstruct individual state labels.

## Decision after the inventory

1. Verify more than one *naturally reached* incoming state in at least one
   ordered source/target condition, with complete trajectories and usable
   target blocks. If there is no such variation, collect additional source
   histories before writing a decision rule.
2. If variation exists, **freeze a separate exploratory replay protocol**:
   select states from real B3 adaptation histories; run each selected state
   and the reference on the **same held-out target evaluation blocks**, with
   target-specific updating disabled. Keep development, calibration, and final
   test blocks disjoint. Run only a small CPU pilot at this stage.
3. Compute the labeled oracle's *upper bound* on the potential value of
   keep-versus-reset. Compare it to an appropriate target-condition-only
   reset and to always-keep. An oracle is not deployable and must never use
   test labels to make real-time decisions. If the oracle has little advantage
   over the simple policy, stop before training a gate or scheduling GPU work.
4. Only after a useful upper bound is established should a new label-free-at-
   deployment decision, equal-budget baselines, and a GPU neural adaptation
   experiment be implemented. Evaluation begins at the actual transition;
   buffering and detection delay count toward service cost.

The inventory is exploratory and is not an IVC resubmission result. Preserve
the old V2.1 tag and release. When a new protocol, scripts, audits, and evidence
are independently frozen and reviewed, merge this branch and create a **new**
versioned tag and release for that evidence; do not tag this preparation step.
