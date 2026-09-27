"""Values layer (Python mirror of web/src/lib/scoring.ts — keep in sync).

Evidence comes in as metric (value, low, high) per scenario × criterion.
Weights come from the user. The two only meet here.
"""

from __future__ import annotations

import numpy as np


def normalize(values: np.ndarray, higher_is_better: np.ndarray) -> np.ndarray:
    """Min–max normalize each criterion (column) to 0–1 across scenarios, so that
    1 is always best. A column with no spread scores 0.5 for everyone."""
    v = np.asarray(values, dtype=float)
    lo, hi = v.min(axis=-2, keepdims=True), v.max(axis=-2, keepdims=True)
    span = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        n = np.where(span > 0, (v - lo) / np.where(span > 0, span, 1), 0.5)
    return np.where(higher_is_better, n, 1 - n)


def scores(values: np.ndarray, higher_is_better: np.ndarray, weights: np.ndarray) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    w = w / w.sum(axis=-1, keepdims=True)
    return (normalize(values, higher_is_better) * w[..., None, :]).sum(axis=-1)


def dirichlet(rng: np.random.Generator, alpha: np.ndarray, n: int) -> np.ndarray:
    return rng.dirichlet(alpha, size=n)


def smaa(value: np.ndarray, low: np.ndarray, high: np.ndarray, higher_is_better: np.ndarray,
         samples: int, seed: int, center: np.ndarray | None = None, concentration: float = 40) -> np.ndarray:
    """Rank-acceptability indices: acc[i, r] = share of draws where scenario i has rank r (0 = best).

    Weights ~ Dirichlet(1,...,1) (uniform on the simplex) or centered on a
    stakeholder profile; metric values ~ Uniform[low, high] independently.
    """
    rng = np.random.default_rng(seed)
    m, k = value.shape
    alpha = np.ones(k) if center is None else np.maximum(center / center.sum() * concentration, 1e-3)
    W = dirichlet(rng, alpha, samples)
    X = rng.uniform(low[None], high[None], size=(samples, m, k))
    S = scores(X, higher_is_better, W)  # (samples, m)
    order = np.argsort(-S, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[np.arange(samples)[:, None], order] = np.arange(m)[None, :]
    acc = np.zeros((m, m))
    for r in range(m):
        acc[:, r] = (ranks == r).mean(axis=0)
    return acc


def ranking_flip(value: np.ndarray, higher_is_better: np.ndarray, weights: np.ndarray) -> dict | None:
    """Smallest change to a single weight that lets the runner-up overtake the top scenario.

    Setting criterion j's normalized weight to t (others rescaled by (1-t)/(1-w_j)
    so weights still sum to 1) makes the score gap linear in t:
        gap(t) = R (1-t)/(1-w_j) + D_j t,   D = N[top] - N[runner_up],  R = D·w - D_j w_j
    so the crossing is t* = r / (r - D_j) with r = R / (1-w_j).
    """
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    s = scores(value, higher_is_better, w)
    order = np.argsort(-s, kind="stable")
    if len(order) < 2:
        return None
    a, b = int(order[0]), int(order[1])
    N = normalize(value, higher_is_better)
    D = N[a] - N[b]
    best: dict | None = None
    for j in range(len(w)):
        if 1 - w[j] <= 1e-12:
            continue
        r = (D @ w - D[j] * w[j]) / (1 - w[j])
        denom = r - D[j]
        if abs(denom) < 1e-12:
            continue
        t = r / denom
        if not (0 <= t <= 1):
            continue
        d = t - w[j]
        if best is None or abs(d) < abs(best["delta"]):
            best = {"criterion_index": j, "from": float(w[j]), "to": float(t), "delta": float(d),
                    "winner": a, "challenger": b}
    return best


def leverage(value: np.ndarray, low: np.ndarray, high: np.ndarray, higher_is_better: np.ndarray,
             weights: np.ndarray, samples: int, seed: int, center: np.ndarray | None = None,
             concentration: float = 40) -> np.ndarray:
    """How much settling each criterion's evidence would move the leader's rank.

    Mirror of web/src/lib/leverage.ts — keep in sync.

    For each criterion j: collapse its uncertainty band to the central estimate,
    resample with the SAME seed, and report the change in the share of draws where
    the current leader comes first. Sharing one seed makes this a difference of
    matched samples, so most of the Monte Carlo noise cancels and a few hundred
    draws are enough to order the criteria — which is all the work plan needs.

    This is the whole reason a work plan can be prioritised: a question whose
    answer cannot move the ranking is one the user should not pay for yet.

    The sign carries meaning and must be preserved:
      > 0  settling this would confirm the leader more often
      < 0  settling this could unseat the leader
    Both say the question is worth asking; only the magnitude orders them.
    """
    k = value.shape[1]
    if value.shape[0] < 2 or k == 0:
        return np.zeros(k)  # nothing to reorder, so nothing has leverage
    base = smaa(value, low, high, higher_is_better, samples, seed, center, concentration)
    # The leader at the user's actual weights, matching rankOrder's stable sort.
    lead = int(np.argsort(-scores(value, higher_is_better, weights), kind="stable")[0])
    out = np.zeros(k)
    for j in range(k):
        lo, hi = low.copy(), high.copy()
        lo[:, j] = hi[:, j] = value[:, j]
        acc = smaa(value, lo, hi, higher_is_better, samples, seed, center, concentration)
        out[j] = acc[lead, 0] - base[lead, 0]
    return out

