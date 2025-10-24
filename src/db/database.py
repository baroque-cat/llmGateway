#!/usr/bin/env python3

import logging
from typing import List, Set, Dict, Any, Optional
from datetime import datetime

import asyncpg
from asyncpg.pool import Pool

# REFACTORED: Import ConfigAccessor and new Status Enum.
from src.core.accessor import ConfigAccessor
from src.core.models import CheckResult
from src.core.enums import Status, ErrorReason

# --- Module-level setup ---
logger = logging.getLogger(__name__)

# This will hold the connection pool instance after initialization.
_db_pool: Optional[Pool] = None

# REFACTORED: The magic string set is no longer needed.
# The Status enum is now the single source of truth.

# REFACTORED: The database schema has been updated to support the new logic.
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

# --- Component 1: Connection Management (unchanged) ---

async def init_db_pool(dsn: str):
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
        logger.critical(f"Failed to initialize database connection pool: {e}", exc_info=True)
        raise

async def close_db_pool():
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
        raise RuntimeError("Database pool has not been initialized. Call init_db_pool() first.")
    return _db_pool


# --- Component 3: Repositories ---

class ProviderRepository:
    """
    Manages data access for the 'providers' table. (unchanged)
    """
    def __init__(self, pool: Pool):
        self._pool = pool

    async def sync(self, provider_names_from_config: List[str]):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch("SELECT name FROM providers")
                providers_in_db = {row['name'] for row in rows}
                
                new_providers = set(provider_names_from_config) - providers_in_db
                
                if new_providers:
                    to_insert = [(name,) for name in new_providers]
                    await conn.copy_records_to_table('providers', records=to_insert, columns=['name'])
                    logger.info(f"SYNC: Added {len(new_providers)} new providers to the database: {new_providers}")

    async def get_id_map(self) -> Dict[str, int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM providers")
            return {row['name']: row['id'] for row in rows}

class KeyRepository:
    """
    Manages data access for 'api_keys' and 'key_model_status' tables.
    Contains the core logic for syncing, checking, and updating keys.
    """
    def __init__(self, pool: Pool, accessor: ConfigAccessor):
        self._pool = pool
        self.accessor = accessor

    async def sync(self, provider_name: str, keys_from_file: Set[str], provider_id: int, provider_models: List[str]):
        # This method's logic is correct, but the 'key_model_status' insertion
        # needs to be updated for the new 'failing_since' column.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. Get keys for this provider from DB
                rows = await conn.fetch("SELECT id, key_value FROM api_keys WHERE provider_id = $1", provider_id)
                keys_in_db = {row['key_value']: row['id'] for row in rows}
                db_key_values = set(keys_in_db.keys())

                # 2. Add new keys to api_keys table
                new_keys_to_add = list(keys_from_file - db_key_values)
                if new_keys_to_add:
                    to_insert = [(provider_id, key) for key in new_keys_to_add]
                    await conn.copy_records_to_table('api_keys', records=to_insert, columns=['provider_id', 'key_value'])
                    logger.info(f"SYNC: Added {len(new_keys_to_add)} new keys for provider '{provider_name}'.")

                # 3. Remove old keys from api_keys table
                keys_to_remove = db_key_values - keys_from_file
                if keys_to_remove:
                    ids_to_remove = [keys_in_db[val] for val in keys_to_remove]
                    await conn.execute("DELETE FROM api_keys WHERE id = ANY($1::int[])", ids_to_remove)
                    logger.info(f"SYNC: Removed {len(keys_to_remove)} obsolete keys for provider '{provider_name}'.")

                # 4. Sync key_model_status table
                rows = await conn.fetch("SELECT id FROM api_keys WHERE provider_id = $1", provider_id)
                current_key_ids = {row['id'] for row in rows}
                
                if not current_key_ids:
                    return

                rows = await conn.fetch("SELECT key_id, model_name FROM key_model_status WHERE key_id = ANY($1::int[])", list(current_key_ids))
                model_statuses_in_db = {(row['key_id'], row['model_name']) for row in rows}
                
                models_to_add = []
                initial_check_time = datetime.utcnow()
                for key_id in current_key_ids:
                    for model_name in provider_models:
                        if (key_id, model_name) not in model_statuses_in_db:
                            # Add the NULL placeholder for the new 'failing_since' column
                            models_to_add.append((key_id, model_name, 'untested', None, initial_check_time))
                
                if models_to_add:
                    # Update column list to include the new column
                    await conn.copy_records_to_table(
                        'key_model_status',
                        records=models_to_add,
                        columns=['key_id', 'model_name', 'status', 'failing_since', 'next_check_time']
                    )
                    logger.info(f"SYNC: Added {len(models_to_add)} new model status records for provider '{provider_name}'.")

    async def get_keys_to_check(self) -> List[Dict[str, Any]]:
        # REFACTORED: The query now returns `failing_since` and no longer filters by `is_dead`.
        query = """
        SELECT
            k.id AS key_id,
            k.key_value,
            p.name AS provider_name,
            s.model_name AS model_name,
            s.failing_since  -- This is the crucial new piece of data for the probe.
        FROM api_keys AS k
        JOIN key_model_status AS s ON k.id = s.key_id
        JOIN providers AS p ON k.provider_id = p.id
        WHERE s.next_check_time <= NOW() AT TIME ZONE 'utc'
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        results = []
        checked_keys_for_shared_providers = set()
        
        for row in rows:
            provider_name = row['provider_name']
            provider_conf = self.accessor.get_provider(provider_name)

            if provider_conf and provider_conf.shared_key_status:
                key_id = row['key_id']
                if key_id in checked_keys_for_shared_providers:
                    continue
                
                # We still only need to check one model (preferably the default) for shared status keys.
                if row['model_name'] == provider_conf.default_model:
                    results.append(dict(row))
                    checked_keys_for_shared_providers.add(key_id)
            else:
                results.append(dict(row))
        return results

    async def update_status(self, key_id: int, model_name: str, provider_name: str, result: CheckResult, next_check_time: datetime):
        # REFACTORED: This method now contains the core logic for managing `failing_since`.
        status_str = Status.VALID if result.ok else result.error_reason.value
        
        # Use the new Status enum for the assertion.
        assert status_str in Status, f"Attempted to write invalid status '{status_str}' to the database!"

        provider_config = self.accessor.get_provider(provider_name)
        
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # This single, powerful query handles all logic for updating the status and the `failing_since` timestamp.
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
                        -- If the check was successful, clear the failure timestamp.
                        WHEN $6 THEN NULL
                        -- Otherwise (if it failed), set the timestamp to now(), but only if it's not already set.
                        -- This captures the beginning of a continuous failure streak.
                        ELSE COALESCE(failing_since, NOW() AT TIME ZONE 'utc')
                    END
                WHERE {where_clause}
                """

                params = [
                    status_str, next_check_time, result.status_code, result.response_time,
                    result.message[:1000], result.ok
                ]

                if provider_config and provider_config.shared_key_status:
                    where_clause = "key_id = $7"
                    params.append(key_id)
                    await conn.execute(base_query.format(where_clause=where_clause), *params)
                    logger.debug(f"PROPAGATED status for key ID {key_id} to '{status_str}' for all its models.")
                else:
                    where_clause = "key_id = $7 AND model_name = $8"
                    params.extend([key_id, model_name])
                    await conn.execute(base_query.format(where_clause=where_clause), *params)

                # The old logic for flagging keys as 'dead' is now completely removed.

    async def get_available_key(self, provider_name: str, model_name: str) -> Optional[Dict[str, Any]]:
        # REFACTORED: Removed the `k.is_dead = FALSE` check. The gateway only cares about the 'valid' status.
        query = """
            SELECT
                k.id AS key_id,
                k.key_value
            FROM api_keys AS k
            JOIN key_model_status AS s ON k.id = s.key_id
            JOIN providers AS p ON k.provider_id = p.id
            WHERE p.name = $1 AND s.model_name = $2 AND s.status = 'valid'
            ORDER BY RANDOM()
            LIMIT 1
            """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, provider_name, model_name)
        return dict(row) if row else None

    async def get_status_summary(self) -> List[Dict[str, Any]]:
        # This query remains correct and does not need changes.
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
        return [dict(row) for row in rows]

class ProxyRepository:
    def __init__(self, pool: Pool):
        self._pool = pool
    
    async def sync(self, provider_name: str, proxies_from_file: Set[str], provider_id: int):
         # Placeholder for future implementation
         pass


# --- Component 4: Facade ---

class DatabaseManager:
    """
    A facade class that provides a single point of access to all repository objects.
    """
    def __init__(self, accessor: ConfigAccessor):
        pool = get_pool()
        self.providers = ProviderRepository(pool)
        self.keys = KeyRepository(pool, accessor)
        self.proxies = ProxyRepository(pool)

    async def initialize_schema(self):
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
        Performs a simple query to verify that the database connection is alive and valid.
        """
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval('SELECT 1')
                return result == 1
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            return False

    # REFACTORED: The amnesty mechanism is no longer needed with the new stateful probe logic.
    # The entire `run_amnesty` method has been removed.

    async def run_vacuum(self):
        """Executes the VACUUM command to optimize the database."""
        pool = get_pool()
        async with pool.acquire() as conn:
            logger.info("MAINTENANCE: Starting database VACUUM operation...")
            await conn.execute("VACUUM;")
            logger.info("MAINTENANCE: Database VACUUM completed successfully.")

