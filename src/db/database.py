# src/db/database.py

import logging
import random
from datetime import UTC, datetime
from typing import Any, Optional, TypedDict

import asyncpg
from asyncpg.pool import Pool

from src.core.accessor import ConfigAccessor
from src.core.constants import ALL_MODELS_MARKER
from src.core.constants import Status
from src.core.models import CheckResult


class KeyToCheck(TypedDict):
    key_id: int
    key_value: str
    provider_name: str
    model_name: str
    failing_since: Optional[datetime]


class AvailableKey(TypedDict):
    key_id: int
    key_value: str


class StatusSummaryItem(TypedDict):
    provider: str
    model: str
    status: str
    count: int


class ValidKeyForCaching(TypedDict):
    key_id: int
    provider_name: str
    model_name: str
    key_value: str


# --- Module-level setup ---
logger = logging.getLogger(__name__)

# This will hold the connection pool instance after initialization.
_db_pool: Pool | None = None

# The database schema, refactored to support state-aware health checks.
# This schema aligns perfectly with the logic in KeyProbe and the removal of the amnesty service.
DB_SCHEMA = """
-- Table 1: Provider directory (unchanged)
CREATE TABLE IF NOT EXISTS providers (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

-- Table 2: The proxy servers themselves (unchanged)
CREATE TABLE IF NOT EXISTS proxies (
    id SERIAL PRIMARY KEY,
    address TEXT UNIQUE NOT NULL
);

-- Table 3: Health status of a proxy FOR A SPECIFIC PROVIDER (unchanged)
CREATE TABLE IF NOT EXISTS provider_proxy_status (
    proxy_id INTEGER NOT NULL,
    provider_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_checked TIMESTAMPTZ,
    next_check_time TIMESTAMPTZ NOT NULL,
    error_message TEXT,
    PRIMARY KEY (proxy_id, provider_id),
    FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE,
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);

-- Table 4: API keys.
-- REFACTORED: Removed is_dead and dead_since columns. The concept of "dead" is now
-- a dynamic state calculated by the application logic, not a flag in the DB.
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    key_value TEXT NOT NULL,
    UNIQUE (provider_id, key_value),
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);

-- Table 5: Health status for each key-model pair.
-- REFACTORED: Added failing_since to track the start of a continuous failure streak.
CREATE TABLE IF NOT EXISTS key_model_status (
    key_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL,
    failing_since TIMESTAMPTZ NULL, -- Timestamp for when the key started failing.
    last_checked TIMESTAMPTZ,
    next_check_time TIMESTAMPTZ NOT NULL,
    status_code INTEGER,
    response_time REAL,
    error_message TEXT,
    PRIMARY KEY (key_id, model_name),
    FOREIGN KEY (key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

-- Indexes for performance optimization (unchanged)
CREATE INDEX IF NOT EXISTS idx_api_keys_provider_id ON api_keys(provider_id);
CREATE INDEX IF NOT EXISTS idx_key_model_status_status ON key_model_status(status);
CREATE INDEX IF NOT EXISTS idx_proxy_status_next_check_time ON provider_proxy_status(next_check_time);
CREATE INDEX IF NOT EXISTS idx_proxy_status_status ON provider_proxy_status(status);
CREATE INDEX IF NOT EXISTS idx_key_status_next_check_time ON key_model_status(next_check_time);
CREATE INDEX IF NOT EXISTS idx_key_status_gateway_lookup ON key_model_status(status, model_name);
"""

# --- Component 1: Connection Management ---


async def init_db_pool(dsn: str) -> None:
    """
    Initializes the asynchronous connection pool to the PostgreSQL database.
    This should be called once when the application starts.
    """
    global _db_pool
    if _db_pool:
        logger.warning("Database pool already initialized.")
        return
    try:
        _db_pool = await asyncpg.create_pool(dsn=dsn, min_size=5, max_size=20)
        logger.info("Database connection pool initialized successfully.")
    except Exception as e:
        logger.critical(
            f"Failed to initialize database connection pool: {e}", exc_info=True
        )
        raise


async def close_db_pool() -> None:
    """
    Closes the database connection pool gracefully.
    This should be called once when the application shuts down.
    """
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database connection pool closed.")


def get_pool() -> Pool:
    """
    Retrieves the initialized database connection pool.
    """
    if _db_pool is None:
        raise RuntimeError(
            "Database pool has not been initialized. Call init_db_pool() first."
        )
    return _db_pool


# --- Component 2: Repositories ---


class ProviderRepository:
    """
    Manages data access for the 'providers' table.
    """

    def __init__(self, pool: Pool):
        self._pool = pool

    async def sync(self, provider_names_from_config: list[str]) -> None:
        """Ensures the providers table is in sync with the configuration."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch("SELECT name FROM providers")
                providers_in_db = {row["name"] for row in rows}

                new_providers = set(provider_names_from_config) - providers_in_db
                obsolete_providers = providers_in_db - set(provider_names_from_config)

                if new_providers:
                    to_insert = [(name,) for name in new_providers]
                    await conn.copy_records_to_table(
                        "providers", records=to_insert, columns=["name"]
                    )
                    logger.info(
                        f"SYNC: Added {len(new_providers)} new providers to the database: {new_providers}"
                    )

                if obsolete_providers:
                    # Delete obsolete providers. CASCADE will automatically remove
                    # all associated api_keys and key_model_status records.
                    placeholders = ", ".join(
                        f"${i + 1}" for i in range(len(obsolete_providers))
                    )
                    query = f"DELETE FROM providers WHERE name IN ({placeholders})"
                    await conn.execute(query, *list(obsolete_providers))
                    logger.info(
                        f"SYNC: Removed {len(obsolete_providers)} obsolete providers from the database: {obsolete_providers}"
                    )

    async def get_id_map(self) -> dict[str, int]:
        """Fetches a mapping of all provider names to their database IDs."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM providers")
            return {row["name"]: row["id"] for row in rows}


class KeyRepository:
    """
    Manages data access for 'api_keys' and 'key_model_status' tables.
    Contains the core logic for syncing, checking, and updating keys.
    """

    def __init__(self, pool: Pool, accessor: ConfigAccessor):
        self._pool = pool
        self.accessor = accessor

    async def sync(
        self,
        provider_name: str,
        provider_id: int,
        keys_from_file: set[str],
        provider_models: list[str],
    ) -> None:
        """
        Synchronizes keys and their model associations for a single provider.
        This method is a core part of the two-phase synchronization cycle.
        It adds/removes keys and adds/removes key-model status records to match the desired state.
        """
        # Get provider config to check shared_key_status
        provider_config = self.accessor.get_provider(provider_name)
        is_shared_key = provider_config and provider_config.shared_key_status

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Step 1: Sync the `api_keys` table.
                rows = await conn.fetch(
                    "SELECT id, key_value FROM api_keys WHERE provider_id = $1",
                    provider_id,
                )
                db_keys = {row["key_value"]: row["id"] for row in rows}
                db_key_values = set(db_keys.keys())

                # Add new keys
                new_key_values = keys_from_file - db_key_values
                if new_key_values:
                    records_to_add = [(provider_id, key) for key in new_key_values]
                    await conn.copy_records_to_table(
                        "api_keys",
                        records=records_to_add,
                        columns=["provider_id", "key_value"],
                    )
                    logger.info(
                        f"SYNC '{provider_name}': Added {len(new_key_values)} new keys."
                    )

                # Remove old keys
                keys_to_remove = db_key_values - keys_from_file
                if keys_to_remove:
                    ids_to_remove = [db_keys[val] for val in keys_to_remove]
                    await conn.execute(
                        "DELETE FROM api_keys WHERE id = ANY($1::int[])", ids_to_remove
                    )
                    logger.info(
                        f"SYNC '{provider_name}': Removed {len(keys_to_remove)} obsolete keys."
                    )

                # Step 2: Sync the `key_model_status` table.
                rows = await conn.fetch(
                    "SELECT id FROM api_keys WHERE provider_id = $1", provider_id
                )
                current_key_ids_in_db = {row["id"] for row in rows}

                if not current_key_ids_in_db:
                    logger.info(
                        f"SYNC '{provider_name}': No keys exist for this provider, skipping model status sync."
                    )
                    return

                # Calculate the desired state of (key_id, model_name) pairs.
                if is_shared_key:
                    # For shared keys, use ALL_MODELS_MARKER instead of individual models
                    desired_model_state = {
                        (key_id, ALL_MODELS_MARKER) for key_id in current_key_ids_in_db
                    }
                else:
                    desired_model_state = {
                        (key_id, model)
                        for key_id in current_key_ids_in_db
                        for model in provider_models
                    }

                # Get the current state from the DB.
                rows = await conn.fetch(
                    "SELECT key_id, model_name FROM key_model_status WHERE key_id = ANY($1::int[])",
                    list(current_key_ids_in_db),
                )
                current_model_state = {
                    (row["key_id"], row["model_name"]) for row in rows
                }

                # Add new model associations.
                models_to_add = list(desired_model_state - current_model_state)
                if models_to_add:
                    initial_check_time = datetime.now(UTC)
                    records = [
                        (key_id, model, "untested", None, initial_check_time)
                        for key_id, model in models_to_add
                    ]
                    await conn.copy_records_to_table(
                        "key_model_status",
                        records=records,
                        columns=[
                            "key_id",
                            "model_name",
                            "status",
                            "failing_since",
                            "next_check_time",
                        ],
                    )
                    logger.info(
                        f"SYNC '{provider_name}': Added {len(models_to_add)} new key-model associations."
                    )

                # Remove obsolete model associations.
                models_to_remove = list(current_model_state - desired_model_state)
                if models_to_remove:
                    # --- MODIFIED BLOCK START ---
                    # The previous method using UNNEST($1::record[]) is not supported by asyncpg's default codecs.
                    # This new approach dynamically builds a WHERE clause with simple parameters, which is universally compatible.
                    # This is safe from SQL injection because we only generate the structure and use parameterized inputs.

                    conditions: list[str] = []
                    flat_params: list[Any] = []
                    param_idx = 1
                    for key_id, model_name in models_to_remove:
                        # For each pair to remove, create a condition like: (key_id = $1 AND model_name = $2)
                        conditions.append(
                            f"(key_id = ${param_idx} AND model_name = ${param_idx + 1})"
                        )
                        # Add the actual values to a flat list for parameter substitution.
                        flat_params.extend([key_id, model_name])
                        param_idx += 2

                    # Join all conditions with OR to form the final WHERE clause.
                    where_clause = " OR ".join(conditions)
                    query = f"DELETE FROM key_model_status WHERE {where_clause}"

                    # Execute the dynamically built, fully parameterized query.
                    await conn.execute(query, *flat_params)
                    # --- MODIFIED BLOCK END ---
                    logger.info(
                        f"SYNC '{provider_name}': Removed {len(models_to_remove)} obsolete key-model associations."
                    )

    async def get_keys_to_check(
        self, enabled_provider_names: list[str]
    ) -> list[KeyToCheck]:
        """
        Fetches all key-model pairs that are due for a health check.
        It crucially retrieves the `failing_since` timestamp for the probe's logic.

        Args:
            enabled_provider_names: A list of provider names that are currently
                                   enabled in the configuration. Only keys for
                                   these providers will be returned.
        """
        if not enabled_provider_names:
            return []

        query = """
        SELECT
            k.id AS key_id,
            k.key_value,
            p.name AS provider_name,
            s.model_name AS model_name,
            s.failing_since
        FROM api_keys AS k
        JOIN key_model_status AS s ON k.id = s.key_id
        JOIN providers AS p ON k.provider_id = p.id
        WHERE s.next_check_time <= NOW() AT TIME ZONE 'utc'
        AND p.name = ANY($1)
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, enabled_provider_names)

        results: list[KeyToCheck] = []
        checked_keys_for_shared_providers: set[int] = set()

        # This logic handles providers where all keys share a single status (e.g., account-level rate limit).
        # It ensures we only check one model per key for these providers to save resources.
        for row in rows:
            provider_name = row["provider_name"]
            provider_conf = self.accessor.get_provider(provider_name)

            if provider_conf and provider_conf.shared_key_status:
                key_id = row["key_id"]
                if key_id in checked_keys_for_shared_providers:
                    continue

                # For shared keys, we should only have entries with ALL_MODELS_MARKER
                # But we need to resolve to a real model for the actual API call
                if row["model_name"] == ALL_MODELS_MARKER:
                    key_to_check: KeyToCheck = {
                        "key_id": row["key_id"],
                        "key_value": row["key_value"],
                        "provider_name": row["provider_name"],
                        "model_name": row["model_name"],
                        "failing_since": row["failing_since"],
                    }
                    results.append(key_to_check)
                    checked_keys_for_shared_providers.add(key_id)
            else:
                key_to_check: KeyToCheck = {
                    "key_id": row["key_id"],
                    "key_value": row["key_value"],
                    "provider_name": row["provider_name"],
                    "model_name": row["model_name"],
                    "failing_since": row["failing_since"],
                }
                results.append(key_to_check)
        return results

    async def update_status(
        self,
        key_id: int,
        model_name: str,
        provider_name: str,
        result: CheckResult,
        next_check_time: datetime,
    ) -> None:
        """
        Updates the status of a key-model pair based on a check result.
        This method contains the core logic for managing the `failing_since` timestamp.
        """
        status_str = Status.VALID if result.ok else result.error_reason.value

        assert status_str in Status, (
            f"Attempted to write invalid status '{status_str}' to the database!"
        )

        provider_config = self.accessor.get_provider(provider_name)
        actual_model_name = model_name

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                base_query = """
                UPDATE key_model_status
                SET 
                    status = $1, 
                    last_checked = NOW() AT TIME ZONE 'utc', 
                    next_check_time = $2,
                    status_code = $3, 
                    response_time = $4, 
                    error_message = $5,
                    failing_since = CASE
                        WHEN $6 THEN NULL
                        ELSE COALESCE(failing_since, NOW() AT TIME ZONE 'utc')
                    END
                WHERE {where_clause}
                """

                params = [
                    status_str,
                    next_check_time,
                    result.status_code,
                    result.response_time,
                    result.message[:1000],
                    result.ok,
                ]

                if provider_config and provider_config.shared_key_status:
                    where_clause = "key_id = $7 AND model_name = $8"
                    params.extend([key_id, ALL_MODELS_MARKER])
                    await conn.execute(
                        base_query.format(where_clause=where_clause), *params
                    )
                else:
                    where_clause = "key_id = $7 AND model_name = $8"
                    params.extend([key_id, actual_model_name])
                    await conn.execute(
                        base_query.format(where_clause=where_clause), *params
                    )

    async def get_available_key(
        self, provider_name: str, model_name: str
    ) -> Optional[AvailableKey]:
        """
        Retrieves a random available key for a given provider and model using
        the efficient COUNT + OFFSET method.
        """
        # Check if provider has shared_key_status enabled
        provider_config = self.accessor.get_provider(provider_name)
        actual_model_name = model_name
        if provider_config and provider_config.shared_key_status:
            actual_model_name = ALL_MODELS_MARKER

        async with self._pool.acquire() as conn:
            # Step 1: Get the total count of valid keys.
            count_query = """
                SELECT COUNT(k.id)
                FROM api_keys AS k
                JOIN key_model_status AS s ON k.id = s.key_id
                JOIN providers AS p ON k.provider_id = p.id
                WHERE p.name = $1 AND s.model_name = $2 AND s.status = 'valid'
            """
            total_valid_keys = await conn.fetchval(
                count_query, provider_name, actual_model_name
            )

            # Step 2: Handle the edge case of no available keys.
            if not total_valid_keys or total_valid_keys == 0:
                return None

            # Step 3: Generate a random offset and fetch the key.
            random_offset = random.randint(0, total_valid_keys - 1)

            get_key_query = """
                SELECT
                    k.id AS key_id,
                    k.key_value
                FROM api_keys AS k
                JOIN key_model_status AS s ON k.id = s.key_id
                JOIN providers AS p ON k.provider_id = p.id
                WHERE p.name = $1 AND s.model_name = $2 AND s.status = 'valid'
                ORDER BY k.id -- A stable order is required for OFFSET to be meaningful
                OFFSET $3
                LIMIT 1
            """
            row = await conn.fetchrow(
                get_key_query, provider_name, actual_model_name, random_offset
            )

        return {"key_id": row["key_id"], "key_value": row["key_value"]} if row else None

    async def get_status_summary(self) -> list[StatusSummaryItem]:
        """
        Retrieves an aggregated summary of key statuses, grouped by provider, model, and status.
        """
        query = """
            SELECT
                p.name AS provider,
                s.model_name AS model,
                s.status,
                COUNT(s.key_id) AS count
            FROM key_model_status AS s
            JOIN api_keys AS k ON s.key_id = k.id
            JOIN providers AS p ON k.provider_id = p.id
            GROUP BY p.name, s.model_name, s.status
            ORDER BY p.name, s.model_name, s.status
            """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        return [
            {
                "provider": row["provider"],
                "model": row["model"],
                "status": row["status"],
                "count": row["count"],
            }
            for row in rows
        ]

    async def get_all_valid_keys_for_caching(self) -> list[ValidKeyForCaching]:
        """
        Fetches all valid keys across all providers and models in a single query.
        This method is designed to be called periodically to populate the gateway's in-memory cache.
        """
        query = """
        SELECT
            k.id AS key_id,
            p.name as provider_name,
            s.model_name,
            k.key_value
        FROM key_model_status AS s
        JOIN api_keys AS k ON s.key_id = k.id
        JOIN providers AS p ON k.provider_id = p.id
        WHERE s.status = 'valid'
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)

        # Return the raw rows from the database.
        # The GatewayCache is now smart enough to handle the __ALL_MODELS__ marker
        # for providers with shared_key_status=True.
        return [
            {
                "key_id": row["key_id"],
                "provider_name": row["provider_name"],
                "model_name": row["model_name"],
                "key_value": row["key_value"],
            }
            for row in rows
        ]


class ProxyRepository:
    """Manages data access for proxy-related tables."""

    def __init__(self, pool: Pool):
        self._pool = pool

    async def sync(
        self, provider_name: str, proxies_from_file: set[str], provider_id: int
    ) -> None:
        # This remains a placeholder as its implementation is outside the current scope.
        pass


# --- Component 3: Facade ---


class DatabaseManager:
    """
    A facade class that provides a single point of access to all repository objects.
    This simplifies dependency injection in the service layer.
    """

    def __init__(self, accessor: ConfigAccessor):
        pool = get_pool()
        self.providers = ProviderRepository(pool)
        self.keys = KeyRepository(pool, accessor)
        self.proxies = ProxyRepository(pool)

    async def initialize_schema(self) -> None:
        """Creates all database tables if they don't exist."""
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(DB_SCHEMA)
            logger.info("Database schema initialized successfully.")
        except Exception as e:
            logger.critical(f"Failed to initialize database schema: {e}", exc_info=True)
            raise

    async def check_connection(self) -> bool:
        """
        Performs a simple query to verify that the database connection is alive.
        """
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                return result == 1
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            return False

    async def run_vacuum(self) -> None:
        """Executes the VACUUM command to optimize the database."""
        pool = get_pool()
        async with pool.acquire() as conn:
            logger.info("MAINTENANCE: Starting database VACUUM operation...")
            # Using non-transactional block for VACUUM
            await conn.execute("VACUUM;")
            logger.info("MAINTENANCE: Database VACUUM completed successfully.")
