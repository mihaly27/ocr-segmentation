"""Reference implementation for the bounded-adaptation Detection--OCR case study.

This module implements the control layer described in main_case_study.tex:
PSI drift, finite-difference sensitivity weights, exact projection for a diagonal
W-metric with box constraints, and the validation/rollback gate.

It is model-agnostic. Connect `evaluator(theta, env, probe)` to the actual
Detection--OCR pipeline. The built-in demo is synthetic and is NOT paper evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Sequence, Tuple
import math
import numpy as np

Array = np.ndarray
Metrics = Dict[str, float]


def psi(reference: Sequence[float], current: Sequence[float], bins: int = 10,
        eps: float = 1e-6) -> float:
    """Population Stability Index using common quantile bins from reference."""
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    if ref.size == 0 or cur.size == 0:
        raise ValueError("PSI requires non-empty reference and current samples")
    qs = np.linspace(0.0, 1.0, bins + 1)
    edges = np.quantile(ref, qs)
    edges = np.unique(edges)
    if edges.size < 3:
        lo = min(ref.min(), cur.min()) - eps
        hi = max(ref.max(), cur.max()) + eps
        edges = np.linspace(lo, hi, bins + 1)
    edges[0] = -np.inf
    edges[-1] = np.inf
    rh, _ = np.histogram(ref, bins=edges)
    ch, _ = np.histogram(cur, bins=edges)
    rp = rh / max(1, rh.sum())
    cp = ch / max(1, ch.sum())
    return float(np.sum((cp - rp) * np.log((cp + eps) / (rp + eps))))


def aggregate_drift(reference_features: Mapping[str, Sequence[float]],
                    current_features: Mapping[str, Sequence[float]],
                    weights: Mapping[str, float], bins: int = 10) -> Tuple[float, Dict[str, float]]:
    """Weighted PSI across observable environment features."""
    parts: Dict[str, float] = {}
    total = 0.0
    weight_sum = sum(float(weights[k]) for k in weights)
    if weight_sum <= 0:
        raise ValueError("Drift weights must sum to a positive value")
    for k, w in weights.items():
        if k not in reference_features or k not in current_features:
            raise KeyError(f"Missing drift feature: {k}")
        val = psi(reference_features[k], current_features[k], bins=bins)
        parts[k] = val
        total += float(w) * val / weight_sum
    return total, parts


def finite_difference_sensitivity(
    evaluator: Callable[[Array], Sequence[object]],
    theta: Array,
    steps: Array,
    output_distance: Callable[[object, object], float],
) -> Array:
    """Estimate per-coordinate end-to-end sensitivity from paired perturbations.

    evaluator(theta) must return one output object per probe sample. The distance
    is evaluated between +h and -h outputs, matching Eq. (finite-sensitivity).
    """
    theta = np.asarray(theta, dtype=float)
    steps = np.asarray(steps, dtype=float)
    if theta.shape != steps.shape:
        raise ValueError("theta and steps must have the same shape")
    sens = np.zeros_like(theta)
    for j, h in enumerate(steps):
        if h <= 0:
            raise ValueError("Finite-difference steps must be positive")
        plus = theta.copy(); plus[j] += h
        minus = theta.copy(); minus[j] -= h
        y_plus = list(evaluator(plus))
        y_minus = list(evaluator(minus))
        if len(y_plus) != len(y_minus) or not y_plus:
            raise ValueError("Evaluator must return equal non-empty probe outputs")
        sq = [(output_distance(a, b) / (2.0 * h)) ** 2 for a, b in zip(y_plus, y_minus)]
        sens[j] = float(np.mean(sq))
    return sens


def build_diagonal_W(sensitivity: Array, risk_weights: Array, lam: float = 1e-4) -> Array:
    """Diagonal case-study approximation W_jj = lambda + r_j s_j."""
    sensitivity = np.asarray(sensitivity, dtype=float)
    risk_weights = np.asarray(risk_weights, dtype=float)
    if sensitivity.shape != risk_weights.shape:
        raise ValueError("sensitivity and risk_weights must have the same shape")
    if lam <= 0 or np.any(risk_weights <= 0) or np.any(sensitivity < 0):
        raise ValueError("Require lambda>0, risk_weights>0, sensitivity>=0")
    return lam + risk_weights * sensitivity


def weighted_norm(delta: Array, w_diag: Array) -> float:
    delta = np.asarray(delta, dtype=float)
    w_diag = np.asarray(w_diag, dtype=float)
    return float(math.sqrt(np.sum(w_diag * delta * delta)))


def project_box_weighted_ball(raw: Array, current: Array, w_diag: Array,
                              delta: float, lower: Array, upper: Array,
                              iterations: int = 80) -> Array:
    """Project onto box intersected with ||theta-current||_W <= delta.

    With diagonal W, transform z=sqrt(W)(theta-current). Projection of raw_z
    onto a Euclidean ball intersected with coordinate bounds has solution
    z_i(lambda)=clip(raw_z_i/(1+lambda), lb_i, ub_i). Bisection finds lambda.
    """
    raw = np.asarray(raw, dtype=float)
    current = np.asarray(current, dtype=float)
    w = np.asarray(w_diag, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if not (raw.shape == current.shape == w.shape == lower.shape == upper.shape):
        raise ValueError("All parameter arrays must have the same shape")
    if np.any(w <= 0) or delta < 0 or np.any(lower > upper):
        raise ValueError("Invalid W, delta, or bounds")
    if np.any(current < lower) or np.any(current > upper):
        raise ValueError("Current state must satisfy hard bounds")

    sw = np.sqrt(w)
    z_raw = sw * (raw - current)
    z_lo = sw * (lower - current)
    z_hi = sw * (upper - current)

    def z_of(lmbd: float) -> Array:
        return np.clip(z_raw / (1.0 + lmbd), z_lo, z_hi)

    z0 = z_of(0.0)
    if np.linalg.norm(z0) <= delta + 1e-12:
        return current + z0 / sw
    if delta == 0:
        return current.copy()

    lo_l, hi_l = 0.0, 1.0
    while np.linalg.norm(z_of(hi_l)) > delta:
        hi_l *= 2.0
        if hi_l > 1e16:
            raise RuntimeError("Projection bisection failed to bracket solution")
    for _ in range(iterations):
        mid = 0.5 * (lo_l + hi_l)
        if np.linalg.norm(z_of(mid)) > delta:
            lo_l = mid
        else:
            hi_l = mid
    z = z_of(hi_l)
    theta = current + z / sw
    return np.clip(theta, lower, upper)


@dataclass(frozen=True)
class GateThresholds:
    tau_e2e: float
    tau_cer: float
    epsilon_s: float
    latency_max: float
    uncertainty_max: float
    epsilon_q: float


def gate(candidate: Mapping[str, float], current: Mapping[str, float],
         thresholds: GateThresholds,
         beta: Mapping[str, float] | None = None,
         beta_delta_j: float = 0.0) -> Tuple[bool, Dict[str, bool]]:
    """Conservative stable-region gate + task non-inferiority."""
    b = dict(beta or {})
    def ub(k: str) -> float:
        return float(candidate[k]) + float(b.get(k, 0.0))
    def lb(k: str) -> float:
        return float(candidate[k]) - float(b.get(k, 0.0))

    checks = {
        "e2e": lb("e2e") >= thresholds.tau_e2e,
        "cer": ub("cer") <= thresholds.tau_cer,
        "stability": ub("stability") <= thresholds.epsilon_s,
        "latency": ub("latency") <= thresholds.latency_max,
        "uncertainty": ub("uncertainty") <= thresholds.uncertainty_max,
        "noninferiority": (float(candidate["e2e"]) - float(current["e2e"]) - beta_delta_j)
                           >= -thresholds.epsilon_q,
    }
    return all(checks.values()), checks


def trigger(drift: float, uncertainty: float, constraint_violation: bool,
            tau_d: float, tau_u: float) -> bool:
    return bool(drift > tau_d or uncertainty > tau_u or constraint_violation)


def _synthetic_demo() -> None:
    """Smoke-test the controller mechanics with synthetic metrics only."""
    rng = np.random.default_rng(7)
    ref = {"luma": rng.normal(0.50, 0.08, 400), "blur": rng.normal(0.10, 0.02, 400)}
    cur = {"luma": rng.normal(0.36, 0.10, 400), "blur": rng.normal(0.18, 0.04, 400)}
    d, parts = aggregate_drift(ref, cur, {"luma": 0.6, "blur": 0.4})

    theta = np.array([1.00, 0.20, 0.50, 0.35, 0.45])
    raw = np.array([1.18, 0.36, 0.42, 0.18, 0.60])
    sens = np.array([0.7, 1.4, 2.8, 1.1, 1.9])
    risk = np.array([1.0, 1.0, 2.0, 1.5, 1.5])
    w = build_diagonal_W(sens, risk)
    projected = project_box_weighted_ball(
        raw, theta, w, delta=0.22,
        lower=np.array([0.7, 0.0, 0.2, 0.1, 0.2]),
        upper=np.array([1.3, 0.6, 0.8, 0.7, 0.8]),
    )
    assert weighted_norm(projected - theta, w) <= 0.2200001

    thr = GateThresholds(0.80, 0.16, 0.12, 45.0, 0.25, 0.02)
    current = {"e2e": 0.82, "cer": 0.14, "stability": 0.10, "latency": 38.0, "uncertainty": 0.22}
    candidate = {"e2e": 0.84, "cer": 0.12, "stability": 0.09, "latency": 40.0, "uncertainty": 0.20}
    accepted, checks = gate(candidate, current, thr)

    print(f"synthetic drift D={d:.4f}; components={parts}")
    print(f"trigger={trigger(d, current['uncertainty'], False, tau_d=0.10, tau_u=0.30)}")
    print(f"weighted step={weighted_norm(projected-theta, w):.6f}")
    print(f"gate={accepted}; checks={checks}")
    print("NOTE: synthetic smoke test only; not an experimental result.")


if __name__ == "__main__":
    _synthetic_demo()
