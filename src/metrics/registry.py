"""Centralized metric name registry.

All metric name constants live here so that Prometheus,
Grafana, and application code use the same strings without
hard-coding them.  The names are **identical** to the current
values in ``metrics_exporter.py`` and ``db_maintainer.py``
to preserve Grafana dashboard compatibility.
"""

# ---- Key status metrics ----
KEY_STATUS_TOTAL: str = "llm_gateway_keys_total"

# ---- Adaptive batch controller metrics ----
ADAPTIVE_BATCH_SIZE: str = "llm_gateway_adaptive_batch_size"
ADAPTIVE_BATCH_DELAY: str = "llm_gateway_adaptive_batch_delay"
ADAPTIVE_RATE_LIMIT_EVENTS: str = "llm_gateway_adaptive_rate_limit_events_total"
ADAPTIVE_BACKOFF_EVENTS: str = "llm_gateway_adaptive_backoff_events_total"
ADAPTIVE_RECOVERY_EVENTS: str = "llm_gateway_adaptive_recovery_events_total"

# ---- Database maintenance metrics ----
DB_DEAD_TUPLES: str = "llm_gateway_db_dead_tuples"
DB_DEAD_RATIO: str = "llm_gateway_db_dead_ratio"
DB_VACUUM_COUNT: str = "llm_gateway_db_vacuum_count"
DB_PURGED_KEYS: str = "llm_gateway_purged_keys_total"

# ---- Request-level metrics (Gateway) ----
REQUESTS_TOTAL: str = "llm_gateway_requests_total"
REQUEST_DURATION_SECONDS: str = "llm_gateway_request_duration_seconds"

# ---- Upstream transport metrics ----
UPSTREAM_ATTEMPTS_TOTAL: str = "llm_gateway_upstream_attempts_total"
TRANSPORT_FAILURES_TOTAL: str = "llm_gateway_transport_failures_total"
STREAM_DISCONNECTS_TOTAL: str = "llm_gateway_stream_disconnects_total"

# ---- Network outage guard metrics ----
NETWORK_GUARD_DOWN: str = "llm_gateway_network_down"
NETWORK_GUARD_TRIPS_TOTAL: str = "llm_gateway_guard_trips_total"

# ---- Sticky key mode / circuit breaker metrics (Gateway) ----
BREAKER_OPENED_EVENTS: str = "llm_gateway_breaker_opened_total"
BREAKER_CLOSED_EVENTS: str = "llm_gateway_breaker_closed_total"
BREAKER_REOPENED_EVENTS: str = "llm_gateway_breaker_reopened_total"
BREAKER_FAIL_FAST_REQUESTS: str = "llm_gateway_breaker_fail_fast_requests_total"
STICKY_ROTATIONS_WITHOUT_BAN: str = "llm_gateway_sticky_rotations_without_ban_total"

# ---- Convenience: all metric names as a set ----
ALL_METRIC_NAMES: frozenset[str] = frozenset(
    {
        KEY_STATUS_TOTAL,
        ADAPTIVE_BATCH_SIZE,
        ADAPTIVE_BATCH_DELAY,
        ADAPTIVE_RATE_LIMIT_EVENTS,
        ADAPTIVE_BACKOFF_EVENTS,
        ADAPTIVE_RECOVERY_EVENTS,
        DB_DEAD_TUPLES,
        DB_DEAD_RATIO,
        DB_VACUUM_COUNT,
        DB_PURGED_KEYS,
        REQUESTS_TOTAL,
        REQUEST_DURATION_SECONDS,
        UPSTREAM_ATTEMPTS_TOTAL,
        TRANSPORT_FAILURES_TOTAL,
        STREAM_DISCONNECTS_TOTAL,
        NETWORK_GUARD_DOWN,
        NETWORK_GUARD_TRIPS_TOTAL,
        BREAKER_OPENED_EVENTS,
        BREAKER_CLOSED_EVENTS,
        BREAKER_REOPENED_EVENTS,
        BREAKER_FAIL_FAST_REQUESTS,
        STICKY_ROTATIONS_WITHOUT_BAN,
    }
)

# ---- Human-readable descriptions ----
METRIC_DESCRIPTIONS: dict[str, str] = {
    KEY_STATUS_TOTAL: "Total number of API keys by provider and status",
    ADAPTIVE_BATCH_SIZE: "Current adaptive batch size per provider",
    ADAPTIVE_BATCH_DELAY: "Current adaptive batch delay in seconds per provider",
    ADAPTIVE_RATE_LIMIT_EVENTS: (
        "Total number of aggressive (rate-limit) backoff events per provider"
    ),
    ADAPTIVE_BACKOFF_EVENTS: (
        "Total number of moderate (transient-threshold) backoff events per provider"
    ),
    ADAPTIVE_RECOVERY_EVENTS: (
        "Total number of recovery (ramp-up) events per provider"
    ),
    DB_DEAD_TUPLES: "Number of dead tuples per user table",
    DB_DEAD_RATIO: "Dead tuple ratio per user table",
    DB_VACUUM_COUNT: "Total number of VACUUM ANALYZE operations per table",
    DB_PURGED_KEYS: "Total number of API keys purged per provider",
    REQUESTS_TOTAL: "Total number of gateway requests",
    REQUEST_DURATION_SECONDS: "Request duration in seconds",
    UPSTREAM_ATTEMPTS_TOTAL: (
        "Total number of upstream attempts by provider and outcome"
    ),
    TRANSPORT_FAILURES_TOTAL: (
        "Total number of transport-level upstream failures by provider and class"
    ),
    STREAM_DISCONNECTS_TOTAL: (
        "Total number of upstream streaming disconnects by provider"
    ),
    NETWORK_GUARD_DOWN: "1 when the network outage guard is in the DOWN state",
    NETWORK_GUARD_TRIPS_TOTAL: (
        "Total number of network guard DOWN transitions by reason"
    ),
    BREAKER_OPENED_EVENTS: (
        "Total number of circuit breaker CLOSED->OPEN transitions per provider"
    ),
    BREAKER_CLOSED_EVENTS: (
        "Total number of circuit breaker HALF_OPEN->CLOSED recoveries per provider"
    ),
    BREAKER_REOPENED_EVENTS: (
        "Total number of circuit breaker HALF_OPEN->OPEN re-openings per provider"
    ),
    BREAKER_FAIL_FAST_REQUESTS: (
        "Total number of requests served fail-fast while the breaker is OPEN"
    ),
    STICKY_ROTATIONS_WITHOUT_BAN: (
        "Total number of sticky key rotations performed without a database ban"
    ),
}
