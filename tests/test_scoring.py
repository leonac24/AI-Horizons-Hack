import numpy as np

from core.scoring import normalize, ranking_flip, scores, smaa


def test_normalize_respects_direction():
    v = np.array([[1.0, 10.0], [3.0, 20.0], [2.0, 30.0]])
    n = normalize(v, np.array([True, False]))
    assert n[:, 0].tolist() == [0.0, 1.0, 0.5]  # higher is better
    assert n[:, 1].tolist() == [1.0, 0.5, 0.0]  # lower is better


def test_normalize_flat_column_is_neutral():
    n = normalize(np.array([[5.0], [5.0]]), np.array([True]))
    assert n.tolist() == [[0.5], [0.5]]


def test_smaa_indices_sum_to_one():
    rng = np.random.default_rng(0)
    v = rng.uniform(0, 10, (4, 3))
    acc = smaa(v, v * 0.9, v * 1.1, np.array([True, False, True]), samples=500, seed=1)
    assert np.allclose(acc.sum(axis=0), 1) and np.allclose(acc.sum(axis=1), 1)


def test_smaa_is_deterministic_with_seed():
    v = np.array([[1.0, 2.0], [2.0, 1.0]])
    a = smaa(v, v, v, np.array([True, True]), samples=200, seed=3)
    b = smaa(v, v, v, np.array([True, True]), samples=200, seed=3)
    assert np.array_equal(a, b)


def test_ranking_flip_toy():
    # A is better on criterion 0, B on criterion 1. Equal weights -> tie broken toward A
    # only if A leads; make A lead slightly by weights.
    v = np.array([[1.0, 0.0], [0.0, 1.0]])
    hib = np.array([True, True])
    w = np.array([0.6, 0.4])
    assert np.argmax(scores(v, hib, w)) == 0
    flip = ranking_flip(v, hib, w)
    assert flip is not None
    assert abs(flip["to"] - 0.5) < 1e-9 or abs(flip["to"] - 0.5) < 1e-9
    assert abs(flip["delta"]) == 0.1 or abs(abs(flip["delta"]) - 0.1) < 1e-9
    wt = w.copy()
    j = flip["criterion_index"]
    wt = wt * (1 - flip["to"]) / (1 - w[j])
    wt[j] = flip["to"]
    s = scores(v, hib, wt)
    assert abs(s[0] - s[1]) < 1e-9
