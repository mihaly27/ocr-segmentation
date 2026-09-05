Bounded Adaptation V2 and V2.1
Calibration, Confirmation, Activation, and Transition-Entry Carryover Evidence

Zenodo dataset version: 2.1.0

Creators:
Mihály Szabó
Attila Kővári
Gábor Kertész

Related manuscript:
When Reactive Gates Are Too Late: Transition-Entry Carryover Harm in
Stateful Computer-Vision Adaptation

Project repository and versioned software release:
https://github.com/mihaly27/ocr-segmentation
https://github.com/mihaly27/ocr-segmentation/releases/tag/bounded-adaptation-v2.1.0


1. PURPOSE OF THIS DEPOSIT

This deposit contains the frozen evidence packages used to study bounded,
stateful adaptation in a deterministic multi-stage segmentation-OCR pipeline.
The evidence is organized into three chronologically distinct layers:

1. V2 calibration;
2. disjoint V2 confirmation; and
3. the later, separately frozen V2.1 activation and transition-entry challenge.

These layers answer different questions and must not be pooled or interpreted
as one preregistered experiment. In particular, V2.1 was designed after V2
confirmation had been completed. It was frozen before its own execution, but it
was not part of the original V2 plan.

The experimental inputs are synthetic and provide controlled ground-truth
conditions without using real vehicle identifiers or personal data.


2. V2 CALIBRATION

V2 calibration evaluated a prespecified grid of candidate weighted update
radii. Its purpose was to determine which tested radii satisfied the pooled
empirical admissibility criterion and to select the largest admissible tested
value for subsequent confirmation.

The completed grid contains 3,000 runs. All positive radii in the 25-value grid
passed the pooled criterion. The selected value was delta_W = 12.0, with zero
harmful trajectories among 84 informative trajectories and a one-sided exact
95% upper bound of approximately 3.50%.

The calibration evidence is condition-dependent. In particular, only 4 of 40
broken-character trajectories were informative. The selected radius is
therefore an empirically screened grid maximum under the pooled rule, not a
localized optimum, proof of invariance, or safety guarantee.

Associated archive:
Node01_Bounded_Adaptation_Recalibration_V2_2026-08-26.zip

The earlier branch archive preserves the implementation and audit context from
which the V2 protocol was finalized:
Node01_Bounded_Adaptation_Recalibration_Branch_2026-08-22.zip


3. DISJOINT V2 CONFIRMATION

After calibration and selection were complete, the selected configuration was
evaluated on five disjoint confirmation trajectories. These trajectories were
not used to select delta_W.

Confirmation produced a +0.90 percentage-point full-plate accuracy estimate
relative to the fixed controller. The two-sided trajectory-level sign test was
p = 0.0625. The adaptive variants were output-identical, and selected-path
projection did not activate. Consequently, the confirmation evidence does not
identify projection, the gate, or recovery as the cause of the observed
accuracy difference.

Associated archive:
V2_confirmation_evidence.zip


4. V2.1 POST-CONFIRMATION CHALLENGE

V2.1 was introduced only after the V2 confirmation results motivated a more
targeted test of mechanism activation and state carryover. Its inputs and
protocol were separately frozen before execution. V2.1 is therefore a
prospectively frozen follow-up challenge, but it is not part of the original V2
calibration or confirmation plan.

V2.1 contains 18 independent trajectories and 155 state changes. It produced
nine gate rejections and no selected-path projections. Counterfactual
evaluation showed that projection could activate under stress, but this does
not establish a causal selected-path protection effect.

The principal V2.1 result concerns transition entry. Harm occurred in 9 of 12
independent trajectories containing an entry into broken-character drift and
in 0 of 6 trajectories without such an entry. All 9 of 36 harmful directed
transitions targeted broken-character drift. The two-sided trajectory-level
Fisher exact comparison was p = 0.0090.

Associated archive:
V2_1_Activation_Carryover_Challenge_2026-08-30.zip


5. RELATIONSHIP AMONG THE THREE EVIDENCE LAYERS

V2 calibration screens candidate parameter-update radii under the frozen
pooled criterion. V2 confirmation evaluates the selected configuration on new,
disjoint trajectories. V2.1 then probes a limitation revealed by the earlier
stages: a state accepted in one environment may be harmful immediately after
entry into another environment, before target evidence enables a reactive
proposal and validation gate.

Accordingly:

- V2 calibration supports the empirical selection statement.
- V2 confirmation provides an out-of-calibration performance estimate.
- V2.1 provides a targeted test of mechanism activation and directed
  transition-entry carryover.

V2.1 observations are not pooled into the V2 calibration count or used to
retroactively redefine the V2 confirmation hypothesis. Results should be
reported with their original evidence layer and inferential unit.


6. ARCHIVE INVENTORY

Node01_Bounded_Adaptation_Recalibration_Branch_2026-08-22.zip
  Implementation, protocol-development, and audit context preceding the
  finalized V2 execution.

Node01_Bounded_Adaptation_Recalibration_V2_2026-08-26.zip
  Frozen V2 calibration, selection, audit, and reproducibility materials.

V2_confirmation_evidence.zip
  Evidence from the five disjoint V2 confirmation trajectories.

V2_1_Activation_Carryover_Challenge_2026-08-30.zip
  Frozen post-confirmation V2.1 activation and carryover challenge materials.

README.txt
  This description of scope, chronology, and relationships among the evidence
  layers.

SHA256SUMS.txt
  SHA-256 checksums for the deposited files. Generate this file only after the
  final README.txt and archive set have been fixed.


7. REPRODUCIBILITY AND INTERPRETATION BOUNDARY

Use the scripts, input locks, manifests, configuration records, and audit
outputs contained in the corresponding archive. Preserve the separation among
calibration, confirmation, and V2.1 when reproducing analyses.

The deposited results support an auditable parameter-governor scaffold and the
observed transition-entry limitation of reactive validation in this testbed.
They do not establish universal safety, causal protection by projection or
recovery, or compatibility for untested environments, states, or directed
transitions.


8. CITATION, DOI, AND LICENSE

Use the version-specific Zenodo DOI assigned to this 2.1.0 record when citing
the evidence. The DOI for the dataset is distinct from any DOI assigned to the
related article or to a separate preprint.

Reuse is governed by the license and access terms shown in the Zenodo record.
The Zenodo metadata are authoritative for the final creator names, identifiers,
license, publication date, and DOI.
