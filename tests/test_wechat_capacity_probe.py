import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "capacity_probe", Path(__file__).resolve().parents[1] / "deploy/benchmark_wechat_capacity.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_summary_counts_errors_and_nearest_rank_percentiles():
    rows = [{"status": 200, "seconds": i / 10} for i in range(1, 20)]
    rows.append({"status": 503, "seconds": 10, "semantic_ok": False})
    result = probe.summarize(rows, 20)
    assert result["p50_seconds"] == 1
    assert result["p95_seconds"] == 1.9
    assert result["p99_seconds"] == 10
    assert result["successful"] == 19
    assert result["semantic_failures"] == 1
    assert result["requests_per_second"] == 1


def test_summary_empty_and_network_failure():
    assert probe.summarize([], 0)["p95_seconds"] is None
    result = probe.summarize([{"status": 0, "seconds": 20}], 20)
    assert result["statuses"] == {"0": 1}
    assert result["successful"] == 0
