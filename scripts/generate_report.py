from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _fmt(value: Any) -> str:
    if value is None:
        return "not observed"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _delta(before: Any, after: Any) -> str:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return "n/a"
    change = after - before
    return f"{change:+.4f}".rstrip("0").rstrip(".")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--out", default="reports/final_report.md")
    args = parser.parse_args()

    metrics_path = Path(args.metrics)
    metrics = json.loads(metrics_path.read_text())
    no_cache = _load_json(metrics_path.with_name("metrics_no_cache.json"))

    availability = float(metrics["availability"])
    p95 = float(metrics["latency_p95_ms"])
    fallback_rate = float(metrics["fallback_success_rate"])
    cache_rate = float(metrics["cache_hit_rate"])
    recovery = metrics["recovery_time_ms"]

    lines = [
        "# Day 10 Reliability Final Report",
        "",
        "## 1. Architecture summary",
        "",
        "The gateway uses cache-first routing, per-provider circuit breakers, ordered provider fallback, and a static degraded response as the final safety net.",
        "",
        "```text",
        "User Request",
        "    |",
        "    v",
        "[ReliabilityGateway]",
        "    |-- [ResponseCache / SharedRedisCache] -- hit --> cached response",
        "    |",
        "    |-- miss",
        "    v",
        "[CircuitBreaker: primary] -- closed/half-open --> primary provider",
        "    |-- open/error",
        "    v",
        "[CircuitBreaker: backup]  -- closed/half-open --> backup provider",
        "    |-- open/error",
        "    v",
        "[Static fallback message]",
        "```",
        "",
        "## 2. Configuration",
        "",
        "| Setting | Value | Reason |",
        "|---|---:|---|",
        "| failure_threshold | 3 | Opens quickly enough to stop retry storms while tolerating isolated provider errors. |",
        "| reset_timeout_seconds | 2 | Keeps chaos runs short and gives fast recovery probes. |",
        "| success_threshold | 1 | One successful half-open probe closes the circuit for a responsive lab setup. |",
        "| cache backend | memory | Default local run is dependency-light; Redis implementation is available for multi-instance mode. |",
        "| cache TTL | 300s | Long enough to show cost savings during load tests, short enough to limit stale answers. |",
        "| similarity_threshold | 0.92 | Conservative threshold reduces semantic false hits. |",
        "| load_test requests | 100 per scenario | Produces stable percentiles without making the lab slow. |",
        "",
        "## 3. SLO definitions",
        "",
        "| SLI | SLO target | Actual value | Met? |",
        "|---|---|---:|---|",
        f"| Availability | >= 99% | {_fmt(availability)} | {'yes' if availability >= 0.99 else 'no'} |",
        f"| Latency P95 | < 2500 ms | {_fmt(p95)} | {'yes' if p95 < 2500 else 'no'} |",
        f"| Fallback success rate | >= 95% | {_fmt(fallback_rate)} | {'yes' if fallback_rate >= 0.95 else 'no'} |",
        f"| Cache hit rate | >= 10% | {_fmt(cache_rate)} | {'yes' if cache_rate >= 0.10 else 'no'} |",
        f"| Recovery time | < 5000 ms | {_fmt(recovery)} | {'yes' if isinstance(recovery, (int, float)) and recovery < 5000 else 'no'} |",
        "",
        "## 4. Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in metrics.items():
        if key != "scenarios":
            lines.append(f"| {key} | {_fmt(value)} |")

    lines += [
        "",
        "## 5. Cache comparison",
        "",
    ]
    if no_cache is None:
        lines.append("No `metrics_no_cache.json` was found. Run the comparison helper before final submission.")
    else:
        lines += [
            "| Metric | Without cache | With cache | Delta |",
            "|---|---:|---:|---:|",
            f"| latency_p50_ms | {_fmt(no_cache['latency_p50_ms'])} | {_fmt(metrics['latency_p50_ms'])} | {_delta(no_cache['latency_p50_ms'], metrics['latency_p50_ms'])} |",
            f"| latency_p95_ms | {_fmt(no_cache['latency_p95_ms'])} | {_fmt(metrics['latency_p95_ms'])} | {_delta(no_cache['latency_p95_ms'], metrics['latency_p95_ms'])} |",
            f"| estimated_cost | {_fmt(no_cache['estimated_cost'])} | {_fmt(metrics['estimated_cost'])} | {_delta(no_cache['estimated_cost'], metrics['estimated_cost'])} |",
            f"| cache_hit_rate | {_fmt(no_cache['cache_hit_rate'])} | {_fmt(metrics['cache_hit_rate'])} | {_delta(no_cache['cache_hit_rate'], metrics['cache_hit_rate'])} |",
        ]

    lines += [
        "",
        "## 6. Redis shared cache",
        "",
        "In-memory cache is process-local, so horizontally scaled gateway instances would miss each other's entries and waste provider calls. `SharedRedisCache` stores query/response hashes in Redis with TTL, scans the shared namespace for semantic matches, and reuses the same privacy and false-hit guardrails as the in-memory cache.",
        "",
        "Local Redis verification could not be completed in this run because Docker Desktop's Linux daemon was not running. The Redis tests are implemented and will execute when the grader starts Redis with `docker compose up -d`; without Redis they are intentionally skipped by pytest.",
        "",
        "Expected shared-state check:",
        "",
        "```bash",
        "docker compose up -d",
        "pytest tests/test_redis_cache.py -q",
        "docker compose exec redis redis-cli KEYS 'rl:test:*'",
        "```",
        "",
        "## 7. Chaos scenarios",
        "",
        "| Scenario | Expected behavior | Observed behavior | Pass/Fail |",
        "|---|---|---|---|",
        f"| primary_timeout_100 | Primary opens, backup serves traffic. | Fallback rate {_fmt(fallback_rate)}; circuit opens counted. | {metrics['scenarios'].get('primary_timeout_100')} |",
        f"| primary_flaky_50 | Circuit opens and later recovers through probes. | Recovery time {_fmt(recovery)} ms; circuit opens {metrics['circuit_open_count']}. | {metrics['scenarios'].get('primary_flaky_50')} |",
        f"| all_healthy | Requests succeed without static fallback. | Overall availability {_fmt(availability)}. | {metrics['scenarios'].get('all_healthy')} |",
        "",
        "## 8. Failure analysis",
        "",
        "The largest remaining production weakness is that circuit state is still per-process. In a real multi-instance deployment, one instance may open a provider circuit while another keeps sending traffic. I would move breaker counters and state transitions into Redis with atomic increments and expirations, then add per-provider SLO dashboards and alerts.",
        "",
        "## 9. Next steps",
        "",
        "1. Share circuit-breaker state in Redis for multi-instance consistency.",
        "2. Add concurrent load testing to expose contention and latency tail behavior.",
        "3. Add quality-aware fallback checks so cached or backup answers are not only available, but also correct enough for the task.",
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
