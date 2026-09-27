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


# --- leverage: which unknown is actually holding the ranking up ----------------
def _two_by_two():
    """Two scenarios, two criteria. A leads on criterion 0, B on criterion 1."""
    value = np.array([[1.0, 0.0], [0.0, 1.0]])
    hib = np.array([True, True])
    w = np.array([0.6, 0.4])  # A leads at these weights
    return value, hib, w


def test_a_certain_criterion_has_no_leverage():
    """The negative result the work plan depends on: settling something already
    settled cannot change the answer, so it must not be recommended."""
    from core.scoring import leverage
    value, hib, w = np.array([[1.0, 0.0], [0.9, 1.0]]), np.array([True, True]), np.array([0.6, 0.4])
    # Criterion 0's band lets the two cross; criterion 1 is already pinned.
    low = np.array([[0.0, 0.0], [0.0, 1.0]])
    high = np.array([[2.0, 0.0], [2.0, 1.0]])
    lev = leverage(value, low, high, hib, w, samples=400, seed=5, center=w)
    assert lev[1] == 0.0, "a zero-width band cannot buy any certainty"
    assert abs(lev[0]) > 0.0, "the one open band should carry all the leverage"


def test_a_band_that_cannot_change_the_order_has_no_leverage():
    """Subtle but load-bearing: scores are min-max normalised across scenarios, so
    what matters is whether a band can reorder the options on that criterion — not
    how wide it is. A huge band on a criterion one option dominates outright buys
    no certainty, and the work plan is right to say do not pay for it yet.
    """
    from core.scoring import leverage
    value = np.array([[100.0, 0.0], [0.0, 1.0]])
    hib = np.array([True, True])
    w = np.array([0.6, 0.4])
    # A's criterion-0 band is enormous, but it never reaches down to B's 0.
    low = np.array([[1.0, 0.0], [0.0, 1.0]])
    high = np.array([[1000.0, 0.0], [0.0, 1.0]])
    assert np.allclose(leverage(value, low, high, hib, w, samples=300, seed=5, center=w), 0.0)


def test_leverage_is_zero_when_nothing_is_uncertain():
    from core.scoring import leverage
    value, hib, w = _two_by_two()
    lev = leverage(value, value, value, hib, w, samples=200, seed=5, center=w)
    assert np.allclose(lev, 0.0)


def test_leverage_needs_two_scenarios_to_mean_anything():
    from core.scoring import leverage
    v = np.array([[1.0, 2.0]])
    lev = leverage(v, v * 0.5, v * 1.5, np.array([True, True]), np.array([0.5, 0.5]),
                   samples=100, seed=1)
    assert np.allclose(lev, 0.0), "one option cannot be reordered"


def test_leverage_is_deterministic():
    from core.scoring import leverage
    value, hib, w = _two_by_two()
    lo, hi = value * 0.0, value + 1.0
    a = leverage(value, lo, hi, hib, w, samples=300, seed=11, center=w)
    b = leverage(value, lo, hi, hib, w, samples=300, seed=11, center=w)
    assert np.array_equal(a, b)


def test_the_criterion_that_can_unseat_the_leader_carries_more_leverage():
    """Ordering is the point: the work plan must put the question that can actually
    change the answer above one that only jitters a number nobody ranks on."""
    from core.scoring import leverage
    value = np.array([[1.0, 0.0], [0.9, 1.0]])
    hib = np.array([True, True])
    w = np.array([0.55, 0.45])
    # Criterion 0's band lets the two swap places; criterion 1's cannot.
    low = np.array([[0.0, 0.0], [0.0, 0.98]])
    high = np.array([[2.0, 0.02], [2.0, 1.0]])
    lev = leverage(value, low, high, hib, w, samples=600, seed=7, center=w)
    assert abs(lev[0]) > abs(lev[1])



def test_a_criterion_whose_bands_never_overlap_carries_no_leverage():
    """Why "zero leverage" needs careful wording in the UI.

    Real example: infrastructure load separates the housing forms into groups whose
    uncertainty bands never overlap, so no resampling can reorder them. Settling it
    cannot change which option wins — but it can still stop the project, so the
    honest label is "would not change which option ranks first", never "does not
    matter".
    """
    from core.scoring import leverage
    value = np.array([[1.0, 1.0], [9.0, 0.0]])
    hib = np.array([False, True])
    w = np.array([0.5, 0.5])
    low = np.array([[0.8, 1.0], [7.4, 0.0]])
    high = np.array([[1.2, 1.0], [10.6, 0.0]])
    assert leverage(value, low, high, hib, w, samples=300, seed=2, center=w)[0] == 0.0
