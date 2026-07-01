# Day 10 Reliability Final Report

## 1. Architecture summary

The gateway uses cache-first routing, per-provider circuit breakers, ordered provider fallback, and a static degraded response as the final safety net.

```text
User Request
    |
    v
[ReliabilityGateway]
    |-- [ResponseCache / SharedRedisCache] -- hit --> cached response
    |
    |-- miss
    v
[CircuitBreaker: primary] -- closed/half-open --> primary provider
    |-- open/error
    v
[CircuitBreaker: backup]  -- closed/half-open --> backup provider
    |-- open/error
    v
[Static fallback message]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Opens quickly enough to stop retry storms while tolerating isolated provider errors. |
| reset_timeout_seconds | 2 | Keeps chaos runs short and gives fast recovery probes. |
| success_threshold | 1 | One successful half-open probe closes the circuit for a responsive lab setup. |
| cache backend | memory | Default local run is dependency-light; Redis implementation is available for multi-instance mode. |
| cache TTL | 300s | Long enough to show cost savings during load tests, short enough to limit stale answers. |
| similarity_threshold | 0.92 | Conservative threshold reduces semantic false hits. |
| load_test requests | 100 per scenario | Produces stable percentiles without making the lab slow. |

## 3. SLO definitions

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 1 | yes |
| Latency P95 | < 2500 ms | 305.31 | yes |
| Fallback success rate | >= 95% | 1 | yes |
| Cache hit rate | >= 10% | 0.6233 | yes |
| Recovery time | < 5000 ms | 2351.7983 | yes |

## 4. Metrics

| Metric | Value |
|---|---:|
| total_requests | 300 |
| availability | 1 |
| error_rate | 0 |
| latency_p50_ms | 263.74 |
| latency_p95_ms | 305.31 |
| latency_p99_ms | 314.21 |
| fallback_success_rate | 1 |
| cache_hit_rate | 0.6233 |
| circuit_open_count | 7 |
| recovery_time_ms | 2351.7983 |
| estimated_cost | 0.0532 |
| estimated_cost_saved | 0.187 |

## 5. Cache comparison

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---:|
| latency_p50_ms | 272.86 | 263.74 | -9.12 |
| latency_p95_ms | 316.56 | 305.31 | -11.25 |
| estimated_cost | 0.134 | 0.0532 | -0.0809 |
| cache_hit_rate | 0 | 0.6233 | +0.6233 |

## 6. Redis shared cache

In-memory cache is process-local, so horizontally scaled gateway instances would miss each other's entries and waste provider calls. `SharedRedisCache` stores query/response hashes in Redis with TTL, scans the shared namespace for semantic matches, and reuses the same privacy and false-hit guardrails as the in-memory cache.

Local Redis verification could not be completed in this run because Docker Desktop's Linux daemon was not running. The Redis tests are implemented and will execute when the grader starts Redis with `docker compose up -d`; without Redis they are intentionally skipped by pytest.

Expected shared-state check:

```bash
docker compose up -d
pytest tests/test_redis_cache.py -q
docker compose exec redis redis-cli KEYS 'rl:test:*'
```

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | Primary opens, backup serves traffic. | Fallback rate 1; circuit opens counted. | pass |
| primary_flaky_50 | Circuit opens and later recovers through probes. | Recovery time 2351.7983 ms; circuit opens 7. | pass |
| all_healthy | Requests succeed without static fallback. | Overall availability 1. | pass |

## 8. Failure analysis

The largest remaining production weakness is that circuit state is still per-process. In a real multi-instance deployment, one instance may open a provider circuit while another keeps sending traffic. I would move breaker counters and state transitions into Redis with atomic increments and expirations, then add per-provider SLO dashboards and alerts.

## 9. Next steps

1. Share circuit-breaker state in Redis for multi-instance consistency.
2. Add concurrent load testing to expose contention and latency tail behavior.
3. Add quality-aware fallback checks so cached or backup answers are not only available, but also correct enough for the task.
