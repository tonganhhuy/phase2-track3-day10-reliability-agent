"""Tests that validate TODO implementations are complete.

These tests are marked @pytest.mark.todo and @pytest.mark.xfail.
They will FAIL until students implement the TODOs — that's by design.
When all xfail tests unexpectedly PASS, the lab is complete.
"""
import pytest

from reliability_lab.cache import ResponseCache
from reliability_lab.circuit_breaker import CircuitBreaker, CircuitState


@pytest.mark.todo
@pytest.mark.xfail(reason="Students must implement ResponseCache.similarity with n-gram cosine")
def test_similarity_uses_ngrams_not_jaccard() -> None:
    """N-gram similarity should distinguish near-identical phrases better than Jaccard."""
    score = ResponseCache.similarity("circuit breaker pattern", "circuit breaker design")
    assert 0.5 < score < 1.0, "N-gram cosine should give partial similarity"
    low = ResponseCache.similarity("hello", "completely different")
    assert low < 0.3, "Unrelated strings should score very low"


@pytest.mark.todo
@pytest.mark.xfail(reason="Students must implement false-hit detection in ResponseCache.get()")
def test_semantic_cache_should_not_false_hit_different_intent() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.3)
    cache.set("Summarize refund policy for 2024 deadline", "Old refund policy")
    cached, _ = cache.get("Summarize refund policy for 2026 deadline")
    assert cached is None


@pytest.mark.todo
@pytest.mark.xfail(reason="Students must implement privacy guardrails in ResponseCache")
def test_privacy_queries_never_cached() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.3)
    cache.set("password reset for user 456", "Reset link sent")
    assert len(cache._entries) == 0, "Privacy-sensitive queries should not be stored"


@pytest.mark.todo
@pytest.mark.xfail(reason="Students must implement CircuitBreaker.allow_request()")
def test_circuit_breaker_denies_when_open() -> None:
    cb = CircuitBreaker("test", failure_threshold=1, reset_timeout_seconds=10)
    cb.state = CircuitState.OPEN
    cb.opened_at = 0.0  # opened long ago but timeout is 10s
    import time
    cb.opened_at = time.monotonic()  # opened just now
    assert not cb.allow_request(), "OPEN circuit should deny requests before timeout"


@pytest.mark.todo
@pytest.mark.xfail(reason="Students must implement CircuitBreaker.record_failure() with separate HALF_OPEN handling")
def test_half_open_failure_gives_probe_failure_reason() -> None:
    cb = CircuitBreaker("test", failure_threshold=3, reset_timeout_seconds=1)
    cb.state = CircuitState.HALF_OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.transition_log[-1]["reason"] == "probe_failure"


@pytest.mark.todo
@pytest.mark.xfail(reason="Students must implement ReliabilityGateway.complete()")
def test_gateway_routes_through_providers() -> None:
    from reliability_lab.gateway import ReliabilityGateway
    from reliability_lab.providers import FakeLLMProvider
    provider = FakeLLMProvider("p", fail_rate=0.0, base_latency_ms=1, cost_per_1k_tokens=0.001)
    breaker = CircuitBreaker("p", failure_threshold=3, reset_timeout_seconds=1)
    gw = ReliabilityGateway([provider], {"p": breaker})
    result = gw.complete("test")
    assert result.text
    assert result.provider == "p"


@pytest.mark.todo
@pytest.mark.xfail(reason="Students must implement metrics.write_csv()")
def test_metrics_csv_export() -> None:
    from reliability_lab.metrics import RunMetrics
    import tempfile
    import os
    m = RunMetrics(total_requests=10, successful_requests=8, failed_requests=2, latencies_ms=[100.0])
    m.scenarios = {"baseline": "pass"}
    path = os.path.join(tempfile.mkdtemp(), "test.csv")
    m.write_csv(path)
    assert os.path.exists(path)
    content = open(path).read()
    assert "scenario_baseline" in content
