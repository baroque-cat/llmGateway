# src/services/gateway_cache.py

import asyncio
import collections
import logging

from src.core.accessor import ConfigAccessor
from src.core.breaker import KeyCircuitBreaker
from src.core.constants import BreakerState, ErrorReason, KeySelectionMode
from src.core.models import CheckResult
from src.db.database import DatabaseManager
from src.metrics import get_collector
from src.metrics.registry import (
    BREAKER_CLOSED_EVENTS,
    BREAKER_FAIL_FAST_REQUESTS,
    BREAKER_OPENED_EVENTS,
    BREAKER_REOPENED_EVENTS,
    METRIC_DESCRIPTIONS,
    STICKY_ROTATIONS_WITHOUT_BAN,
    TRANSPORT_FAILURES_TOTAL,
    UPSTREAM_ATTEMPTS_TOTAL,
)

logger = logging.getLogger(__name__)


def _inc_provider_metric(metric_name: str, provider_name: str) -> None:
    """
    Increments a per-provider gateway counter metric by one.

    Counters are register-or-retrieve via the singleton metrics collector,
    which keeps this helper compatible with both single-process and
    multiprocess Prometheus backends as well as the in-memory backend.

    Args:
        metric_name: Registry name of the counter to increment.
        provider_name: Provider instance label value.
    """
    counter = get_collector().counter(
        metric_name, METRIC_DESCRIPTIONS[metric_name], ["provider"]
    )
    counter.inc(labels={"provider": provider_name})


def observe_upstream_attempt(provider_name: str, result: CheckResult) -> None:
    """Record one upstream attempt and, if applicable, its transport class.

    This is a lightweight observability hook called after every
    ``provider.proxy_request()`` attempt, independent of the key-selection
    mode (sticky or round-robin).  It deliberately does not touch the
    breaker or the key pool.

    Args:
        provider_name: Provider instance name used as the metric label.
        result: The attempt result returned by the provider.
    """
    outcome = "ok" if result.ok else result.error_reason.value
    attempts = get_collector().counter(
        UPSTREAM_ATTEMPTS_TOTAL,
        METRIC_DESCRIPTIONS[UPSTREAM_ATTEMPTS_TOTAL],
        ["provider", "outcome"],
    )
    attempts.inc(labels={"provider": provider_name, "outcome": outcome})

    if result.transport_class is not None:
        failures = get_collector().counter(
            TRANSPORT_FAILURES_TOTAL,
            METRIC_DESCRIPTIONS[TRANSPORT_FAILURES_TOTAL],
            ["provider", "transport_class"],
        )
        failures.inc(
            labels={
                "provider": provider_name,
                "transport_class": result.transport_class.value,
            }
        )


class GatewayCache:
    """
    Manages high-performance in-memory caches for the API Gateway.

    This class encapsulates the logic for caching authentication tokens and
    pools of available API keys. It is designed to be populated at startup
    and periodically refreshed, providing near-instantaneous data access
    to the gateway service during request processing, thus avoiding direct
    database calls in the hot path.

    The cache also owns the per-provider key selection policy state:
    the selection mode (round-robin or sticky), the per-worker sticky key
    pointer, and the per-provider circuit breaker (active only in sticky
    mode with ``circuit_breaker.enabled``). All of this state is in-memory
    per worker process and is never persisted or shared across workers.
    """

    def __init__(self, accessor: ConfigAccessor, db_manager: DatabaseManager):
        """
        Initializes the GatewayCache with necessary dependencies.

        Args:
            accessor: An instance of ConfigAccessor for safe config access.
            db_manager: An instance of the DatabaseManager for async DB access.
        """
        self.accessor = accessor
        self.db_manager = db_manager

        # Cache for mapping gateway access tokens to provider instance names.
        self._auth_token_map: dict[str, str] = {}

        # Cache now stores tuples of (key_id, key_value)
        # to enable the "fast feedback loop" in the gateway service.
        self._key_pool: dict[str, collections.deque[tuple[int, str]]] = (
            collections.defaultdict(collections.deque)
        )

        # Per-provider key selection mode (defaults to round-robin when absent).
        self._selection_modes: dict[str, KeySelectionMode] = {}

        # Per-provider sticky key pointer: (key_id, key_value). Present only
        # while a sticky pointer is established; cleared on rotation triggers
        # that release the pointer, on key removal, or when the breaker opens.
        self._sticky_pointers: dict[str, tuple[int, str]] = {}

        # Per-provider circuit breakers. Instantiated only for providers with
        # sticky mode AND circuit_breaker.enabled (design D9).
        self._breakers: dict[str, KeyCircuitBreaker] = {}

        # A lock to prevent race conditions during concurrent cache modifications.
        # This lock must be used by ALL methods that write to _key_pool.
        self._refresh_lock = asyncio.Lock()

        self._init_selection_policies()

    def _init_selection_policies(self) -> None:
        """
        Populates per-provider selection modes and circuit breakers from config.

        Performed once at startup. A circuit breaker is instantiated only when
        the provider uses sticky mode and has ``circuit_breaker.enabled``;
        in round-robin mode no breaker exists at all, so the round-robin path
        never consults breaker state.
        """
        for name, config in self.accessor.get_enabled_providers().items():
            policy = config.gateway_policy
            mode = policy.key_selection.mode
            self._selection_modes[name] = mode

            if mode is KeySelectionMode.STICKY:
                logger.info(
                    f"[Gateway Startup] Instance '{name}' key selection: sticky "
                    f"(per-worker sticky pointer, rotation without ban on server errors)."
                )
                if policy.circuit_breaker.enabled:
                    self._breakers[name] = KeyCircuitBreaker(
                        policy.circuit_breaker.to_params()
                    )
                    logger.info(
                        f"[Gateway Startup] Instance '{name}' circuit breaker: enabled."
                    )
                else:
                    logger.info(
                        f"[Gateway Startup] Instance '{name}' circuit breaker: disabled."
                    )

    def _populate_auth_map(self) -> None:
        """
        Populates the authentication token cache from the configuration.
        This is a synchronous operation performed once at startup.
        """
        logger.info("Populating authentication token cache...")
        self._auth_token_map.clear()

        enabled_providers = self.accessor.get_enabled_providers()
        for name, config in enabled_providers.items():
            token = config.access_control.gateway_access_token
            if token:
                if token in self._auth_token_map:
                    # The validator should prevent this, but this is a safeguard.
                    logger.warning(
                        f"Duplicate gateway access token '{token}' found for providers "
                        f"'{self._auth_token_map[token]}' and '{name}'. The latter will be ignored."
                    )
                else:
                    self._auth_token_map[token] = name

        logger.info(
            f"Authentication token cache populated with {len(self._auth_token_map)} tokens."
        )

    async def refresh_key_pool(self) -> None:
        """
        Asynchronously refreshes the API key pool from the database.

        This method fetches all currently valid keys and rebuilds the
        in-memory key pool. It is designed to be called periodically.
        The operation is protected by a lock to ensure atomicity.
        """
        async with self._refresh_lock:
            logger.debug("Refreshing key pool cache from database...")
            try:
                # 1. Fetch all valid keys in a single, efficient query.
                valid_keys_data = (
                    await self.db_manager.keys.get_all_valid_keys_for_caching()
                )

                # 2. Build a new key pool in a temporary variable.
                new_key_pool: collections.defaultdict[
                    str, collections.deque[tuple[int, str]]
                ] = collections.defaultdict(collections.deque)
                for record in valid_keys_data:
                    key_id = record["key_id"]
                    provider_name = record["provider_name"]
                    key_value = record["key_value"]
                    pool_key = provider_name

                    new_key_pool[pool_key].append((key_id, key_value))

                # 3. Atomically replace the old pool with the new one.
                self._key_pool = new_key_pool

                # 4. Re-validate sticky pointers against the rebuilt pools.
                # The pointer identity is the DB key_id: if it is still present,
                # keep the pointer (refreshing the value from the new pool);
                # otherwise clear it so the next request re-establishes it.
                for provider_name in list(self._sticky_pointers):
                    pointer = self._sticky_pointers[provider_name]
                    pool = self._key_pool.get(provider_name)
                    refreshed = next(
                        (info for info in (pool or ()) if info[0] == pointer[0]),
                        None,
                    )
                    if refreshed is None:
                        del self._sticky_pointers[provider_name]
                        logger.debug(
                            f"Sticky pointer for '{provider_name}' cleared: "
                            f"key_id {pointer[0]} is no longer in the pool."
                        )
                    else:
                        self._sticky_pointers[provider_name] = refreshed

                total_keys = sum(len(q) for q in self._key_pool.values())
                logger.debug(
                    f"Key pool cache refreshed successfully. Loaded {total_keys} keys across {len(self._key_pool)} pools."
                )

            except Exception as e:
                logger.critical(
                    "Failed to refresh key pool cache due to a database error.",
                    exc_info=e,
                )

    async def populate_caches(self) -> None:
        """
        Performs the initial population of all caches.
        This should be called once when the gateway service starts.
        """
        self._populate_auth_map()
        await self.refresh_key_pool()

    def get_instance_name_by_token(self, token: str) -> str | None:
        """
        Retrieves the provider instance name associated with a gateway access token.

        Args:
            token: The gateway access token from the request headers.

        Returns:
            The provider instance name if the token is valid, otherwise None.
        """
        return self._auth_token_map.get(token)

    def get_selection_mode(self, provider_name: str) -> KeySelectionMode:
        """
        Retrieves the configured key selection mode for a provider.

        Args:
            provider_name: The name of the provider instance.

        Returns:
            The configured ``KeySelectionMode``; ``ROUND_ROBIN`` when the
            provider has no explicit mode configured.
        """
        return self._selection_modes.get(provider_name, KeySelectionMode.ROUND_ROBIN)

    def get_sticky_pointer(self, provider_name: str) -> tuple[int, str] | None:
        """
        Retrieves the current sticky key pointer for a provider, if any.

        Args:
            provider_name: The name of the provider instance.

        Returns:
            The sticky pointer ``(key_id, key_value)`` when established,
            otherwise None.
        """
        return self._sticky_pointers.get(provider_name)

    def get_breaker(self, provider_name: str) -> KeyCircuitBreaker | None:
        """
        Retrieves the circuit breaker for a provider, if one is active.

        Args:
            provider_name: The name of the provider instance.

        Returns:
            The ``KeyCircuitBreaker`` for sticky providers with the breaker
            enabled, otherwise None.
        """
        return self._breakers.get(provider_name)

    def _is_sticky_effective(self, provider_name: str) -> bool:
        """
        Determines whether sticky selection applies for the next pick.

        Sticky selection is effective only when the provider is configured
        for sticky mode AND its circuit breaker (if any) is CLOSED. While the
        breaker is OPEN or HALF_OPEN, the sticky pointer is released and
        selection falls back to round-robin so probe traffic spreads across
        the pool (design D7).

        Args:
            provider_name: The name of the provider instance.

        Returns:
            True when sticky selection should be used for this provider.
        """
        if self._selection_modes.get(provider_name) is not KeySelectionMode.STICKY:
            return False
        breaker = self._breakers.get(provider_name)
        return breaker is None or breaker.state is BreakerState.CLOSED

    def get_key_from_pool(
        self,
        provider_name: str,
        exclude_key_ids: set[int] | None = None,
    ) -> tuple[int, str] | None:
        """
        Retrieves one available API key from the specified pool.

        The selection strategy depends on the provider's configured key
        selection mode. In ``round_robin`` mode (default) the selected key is
        rotated to the back of the deque, exactly as before the sticky mode
        was introduced. In ``sticky`` mode the sticky pointer key is returned
        without rotating the deque; when the pointer is unset (or its key is
        excluded/absent), a new pointer is established from the pool.

        This operation is performed in O(1) time for established sticky
        pointers and is NOT locked to ensure maximum performance for read
        operations. `deque` operations are atomic.

        Args:
            provider_name: The name of the provider instance.
            exclude_key_ids: A set of key IDs to ignore during selection.

        Returns:
            A tuple of (key_id, key_value) if a key is available, otherwise None.
        """
        if self._is_sticky_effective(provider_name):
            pointer = self._sticky_pointers.get(provider_name)
            if pointer is not None and not (
                exclude_key_ids and pointer[0] in exclude_key_ids
            ):
                pool = self._key_pool.get(provider_name)
                if pool is not None and any(key_id == pointer[0] for key_id, _ in pool):
                    # Sticky hit: return the pointer key WITHOUT rotating
                    # the deque.
                    return pointer
            # Pointer unset, excluded, or stale: (re-)establish it.
            return self._establish_sticky_pointer(provider_name, exclude_key_ids)

        return self._get_key_round_robin(provider_name, exclude_key_ids)

    def _get_key_round_robin(
        self,
        provider_name: str,
        exclude_key_ids: set[int] | None = None,
    ) -> tuple[int, str] | None:
        """
        Retrieves one available API key using round-robin rotation.

        This is the original selection behavior: the key at the front of the
        deque is moved to the back on every call. Used for round-robin
        providers, for sticky pointer establishment/rotation, and as the
        fallback probe selection while a circuit breaker is not CLOSED.

        Args:
            provider_name: The name of the provider instance.
            exclude_key_ids: A set of key IDs to ignore during selection.

        Returns:
            A tuple of (key_id, key_value) if a key is available, otherwise None.
        """
        pool_key = provider_name

        key_queue = self._key_pool.get(pool_key)

        if key_queue:
            attempts = len(key_queue)
            for _ in range(attempts):
                try:
                    # Get a key tuple from the left (front) of the deque.
                    key_info = key_queue.popleft()
                    # Append it to the right (back) to rotate it.
                    key_queue.append(key_info)

                    if exclude_key_ids and key_info[0] in exclude_key_ids:
                        continue

                    return key_info
                except IndexError:
                    # This can happen in a rare race condition if the pool becomes empty
                    # between the 'if' check and 'popleft' because of a concurrent removal.
                    return None

        return None

    def _establish_sticky_pointer(
        self,
        provider_name: str,
        exclude_key_ids: set[int] | None = None,
    ) -> tuple[int, str] | None:
        """
        Selects a new sticky key and binds the sticky pointer to it.

        The new key is taken from the pool via the round-robin scan honoring
        the exclusion set, so failed keys are never re-selected. When no key
        is available, the pointer is cleared and None is returned.

        Args:
            provider_name: The name of the provider instance.
            exclude_key_ids: A set of key IDs to ignore during selection.

        Returns:
            The newly bound ``(key_id, key_value)``, or None when the pool
            has no usable key.
        """
        key_info = self._get_key_round_robin(provider_name, exclude_key_ids)
        if key_info is None:
            self._sticky_pointers.pop(provider_name, None)
            return None
        self._sticky_pointers[provider_name] = key_info
        return key_info

    def rotate_sticky_key(
        self,
        provider_name: str,
        exclude_key_ids: set[int] | None = None,
    ) -> tuple[int, str] | None:
        """
        Rotates the sticky pointer to a new key excluding the failed keys.

        Used by the request handlers when a rotation trigger fires. When
        sticky selection is not effective (round-robin mode, or the breaker
        is OPEN/HALF_OPEN and the pointer is released), no pointer is bound
        and None is returned.

        Args:
            provider_name: The name of the provider instance.
            exclude_key_ids: A set of failed key IDs to exclude.

        Returns:
            The new sticky ``(key_id, key_value)``, or None when sticky
            selection is not effective or no other key is available.
        """
        if not self._is_sticky_effective(provider_name):
            return None
        return self._establish_sticky_pointer(provider_name, exclude_key_ids)

    def should_fail_fast(self, provider_name: str) -> bool:
        """
        Queries the provider's circuit breaker whether to fail fast.

        Also drives the OPEN -> HALF_OPEN transition once the cooldown has
        elapsed. Providers without a breaker (round-robin mode or breaker
        disabled) never fail fast.

        Args:
            provider_name: The name of the provider instance.

        Returns:
            True when the request must bypass retries and make exactly one
            upstream attempt with transparent error forwarding.
        """
        breaker = self._breakers.get(provider_name)
        if breaker is None:
            return False
        fail_fast = breaker.should_fail_fast()
        if fail_fast:
            _inc_provider_metric(BREAKER_FAIL_FAST_REQUESTS, provider_name)
        return fail_fast

    def record_upstream_result(
        self,
        provider_name: str,
        ok: bool,
        error_reason: ErrorReason | None = None,
        key_info: tuple[int, str] | None = None,
    ) -> None:
        """
        Records an upstream attempt outcome into the provider's circuit breaker.

        No-op for providers without a breaker. Drives the breaker state
        machine and applies the pointer side effects of transitions:
        the sticky pointer is released while the breaker is OPEN/HALF_OPEN,
        and re-bound to the last successful key when probe successes close
        the breaker (design D7-D8).

        Args:
            provider_name: The name of the provider instance.
            ok: True when the upstream attempt succeeded.
            error_reason: The final refined ``ErrorReason`` on failure.
            key_info: The ``(key_id, key_value)`` used for the attempt; used
                to bind the sticky pointer when the breaker closes.
        """
        breaker = self._breakers.get(provider_name)
        if breaker is None:
            return

        previous_state = breaker.state
        breaker.record_result(ok, error_reason)
        new_state = breaker.state

        if new_state in (BreakerState.OPEN, BreakerState.HALF_OPEN):
            # While the breaker is not closed, the sticky pointer is released
            # and selection falls back to round-robin probe traffic.
            self._sticky_pointers.pop(provider_name, None)

        if previous_state is BreakerState.CLOSED and new_state is BreakerState.OPEN:
            _inc_provider_metric(BREAKER_OPENED_EVENTS, provider_name)
            logger.warning(
                f"Circuit breaker for '{provider_name}' OPENED: retryable error "
                f"share exceeded the threshold. Fail-fast active, bans frozen "
                f"for retryable errors, sticky pointer released."
            )
        elif (
            previous_state is BreakerState.HALF_OPEN and new_state is BreakerState.OPEN
        ):
            _inc_provider_metric(BREAKER_REOPENED_EVENTS, provider_name)
            logger.warning(
                f"Circuit breaker for '{provider_name}' RE-OPENED after a failed "
                f"probe. Cooldown grew to {breaker.current_cooldown:.1f}s."
            )
        elif (
            previous_state is BreakerState.HALF_OPEN
            and new_state is BreakerState.CLOSED
        ):
            _inc_provider_metric(BREAKER_CLOSED_EVENTS, provider_name)
            logger.info(
                f"Circuit breaker for '{provider_name}' CLOSED after "
                f"{breaker.probe_successes} consecutive probe successes. "
                f"Sticky selection re-engaged."
            )
            if ok and key_info is not None:
                # Bind the sticky pointer to the last successful probe key.
                self._sticky_pointers[provider_name] = key_info

    def note_rotation_without_ban(self, provider_name: str) -> None:
        """
        Records a sticky key rotation performed without a database ban.

        Observability hook for the sticky penalty semantics: server errors
        rotate the key without penalizing it (design D4).

        Args:
            provider_name: The name of the provider instance.
        """
        _inc_provider_metric(STICKY_ROTATIONS_WITHOUT_BAN, provider_name)

    async def remove_key_from_pool(self, provider_name: str, key_id: int) -> None:
        """
        Immediately removes a specific key from the live key pool cache.

        This is a write operation and is protected by a lock.

        Args:
            provider_name: The name of the provider instance.
            key_id: The database ID of the key to remove.
        """
        async with self._refresh_lock:
            pool_key = provider_name
            self._remove_from_single_pool(pool_key, key_id)

    def _remove_from_single_pool(self, pool_key: str, key_id: int) -> None:
        """
        A private helper to perform the removal logic on a single key pool.
        This avoids code duplication.
        """
        key_queue = self._key_pool.get(pool_key)

        if not key_queue:
            return  # The pool is already empty or doesn't exist.

        initial_size = len(key_queue)

        # Re-create the deque, excluding the key with the matching ID.
        new_queue = collections.deque([info for info in key_queue if info[0] != key_id])

        if len(new_queue) < initial_size:
            self._key_pool[pool_key] = new_queue
            # Clear the sticky pointer when it holds the removed key, so the
            # next request re-establishes it from the remaining pool.
            pointer = self._sticky_pointers.get(pool_key)
            if pointer is not None and pointer[0] == key_id:
                del self._sticky_pointers[pool_key]
                logger.debug(
                    f"Sticky pointer for '{pool_key}' cleared: "
                    f"it held the removed key_id {key_id}."
                )
            logger.debug(
                f"Removed failed key_id {key_id} from live cache pool '{pool_key}'. "
                f"Pool size changed from {initial_size} to {len(new_queue)}."
            )
        else:
            # This is not an error, just means the key was already removed by another coroutine.
            logger.debug(
                f"Attempted to remove key_id {key_id} from pool '{pool_key}', but it was not found."
            )
