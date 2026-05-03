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
    }
)

# ---- Human-readable descriptions ----
METRIC_DESCRIPTIONS: dict[str, str] = {
    KEY_STATUS_TOTAL: "Total number of API keys by provider, model, and status",
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
}
