"""Phase 5 benchmark math + live-flag gating (offline only)."""

import phase5_benchmark as benchmark


def test_stats_empty():
    stats = benchmark._stats([])
    assert stats["count"] == 0
    assert stats["min_ms"] is None
    assert stats["p50_ms"] is None
    assert stats["mean_ms"] is None


def test_stats_single_value():
    stats = benchmark._stats([12.5])
    assert stats == {"count": 1, "min_ms": 12.5, "p50_ms": 12.5,
                     "p95_ms": 12.5, "max_ms": 12.5, "mean_ms": 12.5}


def test_stats_percentiles_monotonic():
    values = [float(n) for n in range(1, 101)]
    stats = benchmark._stats(values)
    assert stats["min_ms"] == 1.0
    assert stats["max_ms"] == 100.0
    assert stats["min_ms"] <= stats["p50_ms"] <= stats["p95_ms"] \
        <= stats["max_ms"]
    assert abs(stats["p50_ms"] - 50.5) < 1e-9
    assert abs(stats["mean_ms"] - 50.5) < 1e-9


def test_partial_live_flags_rejected():
    assert benchmark.main(["--live"]) == 2
    assert benchmark.main(["--allow-billable"]) == 2


def test_live_provider_set_is_bounded():
    assert set(benchmark.LIVE_PROVIDERS) == {
        "meta-spark", "meta-voice", "meta-sam", "baseten"}
