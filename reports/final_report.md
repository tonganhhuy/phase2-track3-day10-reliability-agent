# Day 10 Reliability Final Report

## 1. Architecture summary

The reliable LLM agent gateway acts as a proxy between users and upstream LLM providers, ensuring high availability, cost saving, and graceful degradation under load or system failure. It consists of the following layers:

1. **Semantic Cache**:
   - First line of defense.
   - Utilizes **cosine similarity over word tokens and character 3-grams** to find semantically similar queries.
   - Includes **privacy guardrails** (regex filters to block password, balance, and account-number queries from being cached or served from cache).
   - Includes **false-hit detection** (rejects similarity hits if the query and cache entry contain mismatching 4-digit numbers, e.g. different years/IDs).
   - Supports both local in-memory backend (`ResponseCache`) and shared Redis backend (`SharedRedisCache`).

2. **Circuit Breaker state machine**:
   - Implemented as a 3-state machine (`CLOSED`, `OPEN`, `HALF_OPEN`) per provider.
   - Failures are recorded and transition the circuit to `OPEN` if the `failure_threshold` is reached, preventing retry storms on failing providers.
   - Fast-fails requests during the `reset_timeout` window.
   - Probes the provider with a single request after the timeout. If successful, transitions back to `CLOSED`. If it fails, transitions back to `OPEN`.

3. **Gateway fallback chain**:
   - Iterates through the list of providers in order (Primary -> Backup).
   - If a provider's circuit is CLOSED or HALF-OPEN, the request is attempted.
   - On success, the response is returned and cached.
   - On failure (or if the circuit is OPEN), the gateway catches the error, registers it, and falls back to the next provider.

4. **Static fallback**:
   - If all providers fail, returns a static degraded message to the user: *"The service is temporarily degraded. Please try again soon."*

### Architecture Diagram

```
User Request
    |
    v
[Gateway] ---> [Cache check (Memory/Redis)] ---> HIT? (Check false-hit & privacy) ---> return cached
    |                                                                                         |
    v                                                                                         v NO / MISS
[Circuit Breaker: Primary] ---------------------------> Call Primary Provider
    |  (OPEN? fail fast & check next)                             | (Success? cache & return)
    v                                                             v (Failure? record & fallback)
[Circuit Breaker: Backup] ----------------------------> Call Backup Provider
    |  (OPEN? fail fast & check next)                             | (Success? cache & return)
    v                                                             v (Failure? record & fallback)
[Static fallback message] <---------------------------------------+
```

---

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Allows minor temporary network glitches but opens quickly on persistent errors. |
| reset_timeout_seconds | 2.0 | Short cool-off period suitable for dynamic local testing/recovery. |
| success_threshold | 1 | A single successful request in HALF_OPEN is sufficient to prove recovery. |
| cache TTL | 300 | Caches responses for 5 minutes, reducing upstream costs without serving overly stale data. |
| similarity_threshold | 0.92 | High threshold to ensure only closely related queries trigger cache hits, preventing semantic drift. |
| load_test requests | 100 | Sufficient sample size to evaluate statistical metrics (P50/P95/P99 latency, cost). |

---

## 3. SLO definitions

Define your target SLOs and whether your system meets them:

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 98.33% | No (due to extreme chaos scenarios where all providers failed temporarily) |
| Latency P95 | < 2500 ms | 319.43 ms | Yes (well under the limit due to fast fake provider response time) |
| Fallback success rate | >= 95% | 92.65% | No (due to concurrent failure of backup provider in timeout scenarios) |
| Cache hit rate | >= 10% | 70.67% | Yes (very high cache hit rate under the test query distributions) |
| Recovery time | < 5000 ms | 2348.17 ms | Yes (within the 2-second timeout window plus minor network delay) |

---

## 4. Metrics

Summary of metrics gathered under chaos simulation (`reports/metrics.json` using Redis cache):

| Metric | Value |
|---|---:|
| availability | 0.9833 |
| error_rate | 0.0167 |
| latency_p50_ms | 287.53 |
| latency_p95_ms | 319.43 |
| latency_p99_ms | 329.74 |
| fallback_success_rate | 0.9265 |
| cache_hit_rate | 0.7067 |
| estimated_cost_saved | 0.212000 |
| circuit_open_count | 9 |
| recovery_time_ms | 2348.17 |

---

## 5. Cache comparison

Metrics comparison between cache disabled vs enabled:

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | 278.11 ms | 287.53 ms | +9.42 ms |
| latency_p95_ms | 318.39 ms | 319.43 ms | +1.04 ms |
| estimated_cost | $0.118120 | $0.032700 | -$0.085420 (72.3% cost saved) |
| cache_hit_rate | 0.0 | 0.7067 | +0.7067 |

> [!NOTE]
> Latencies represent response times for provider-based requests. Since cache-hits return with `latency_ms = 0.0`, they are excluded from the P50/P95 latency of upstream requests.

---

## 6. Redis shared cache

### Why shared cache matters for production

- **Why in-memory cache is insufficient for multi-instance deployments**: In-memory caching resides inside the RAM of a single process/machine. In production environments, gateways are scaled horizontally (multiple Docker containers behind a load balancer). If a request hits Container A, only Container A caches it. When a duplicate request hits Container B, it misses and issues a duplicate query to the LLM, increasing latency and cost.
- **How `SharedRedisCache` solves this**: By storing the keys and responses in a centralized Redis cluster, all instances query the same shared cache. This yields maximum cache efficiency and guarantees consistent cost savings regardless of which instance serves the request.

### Evidence of shared state

Two `SharedRedisCache` instances accessing the same Redis keyspace. Running unit tests proves that they share cache state successfully:

```
tests\test_redis_cache.py ......                                         [100%]
============================== 6 passed in 8.28s ==============================
```

Specifically, `test_shared_state_across_instances` sets data in cache instance `c1` and asserts that instance `c2` can read it:

```python
def test_shared_state_across_instances() -> None:
    c1 = SharedRedisCache(redis_url="redis://localhost:6379/0", ttl_seconds=60, similarity_threshold=0.5, prefix="rl:test:shared:")
    c2 = SharedRedisCache(redis_url="redis://localhost:6379/0", ttl_seconds=60, similarity_threshold=0.5, prefix="rl:test:shared:")
    c1.set("shared query", "shared response")
    cached, _ = c2.get("shared query")
    assert cached == "shared response"
```

### Redis CLI output

Querying the Redis database inside the Docker container lists the stored semantic cache entry hashes:

```bash
$ docker compose exec redis redis-cli KEYS "rl:cache:*"
rl:cache:4fc3c69b9376
rl:cache:3dab98c0e49e
rl:cache:da61fb49b4f6
rl:cache:844ef0143a5c
rl:cache:734852f3cf4a
rl:cache:98332d0d1c9c
rl:cache:d354658dc020
rl:cache:0bc3b1acf73d
rl:cache:fff10da1c72c
rl:cache:dacb2b833659
rl:cache:3936614ac4c2
rl:cache:9e413fd814eb
rl:cache:095946136fea
```

---

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | All traffic fallback to backup, primary circuit opens | Primary failed 100% of the time, primary circuit opened, backup served traffic successfully | Pass |
| primary_flaky_50 | Primary circuit oscillates, mix of primary and fallback | Circuit transitioned between open and closed, traffic split between primary and backup | Pass |
| all_healthy | All requests via primary, no circuit opens | All 100 requests processed by primary, zero circuit transitions | Pass |

---

## 8. Failure analysis

### Remaining Weakness
The **circuit breaker state** is currently kept **in-memory** on each gateway instance. If primary provider starts failing, Instance A will open its circuit breaker, but Instance B won't know until it queries the provider and fails `failure_threshold` times. This results in **duplicate upstream failures** and delayed fast-fail transitions across instances.

### Production Solution
To solve this, store the circuit breaker state (failure counts, current state, `opened_at` timestamp) in **Redis**.
- Use Redis `INCR` and `EXPIRE` commands to track failures globally.
- Use a Redis key `rl:breaker:{provider_name}:state` to share state (CLOSED/OPEN/HALF_OPEN).
- Instances fetch the state from Redis on `allow_request()` to ensure global synchronization.

---

## 9. Next steps

List of concrete improvements:

1. **Distributed Circuit Breakers**: Share circuit breaker state globally using Redis, avoiding duplicate failures on separate gateway instances.
2. **Graceful Cache Degradation**: Add fallback logic so that if Redis goes down, the gateway gracefully falls back to an in-memory cache instead of raising exceptions.
3. **Cost-aware and SLO-aware Routing**: Automatically reroute traffic to a cheaper backup model if the cumulative budget exceeds 80%, and fall back to cache-only if 100% budget is reached.
