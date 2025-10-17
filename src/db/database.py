# src/db/database.py

import logging
from typing import List, Set, Dict, Any, Optional
from datetime import datetime

import asyncpg
from asyncpg.pool import Pool

from src.config.schemas import Config
from src.core.models import CheckResult
from src.core.enums import ErrorReason

# --- Module-level setup ---
logger = logging.getLogger(__name__)

# This will hold the connection pool instance after initialization.
_db_pool: Optional[Pool] = None

# --- Data Integrity Contract ---
# Create a set of all valid string values for the status field.
# This acts as a programmatic guard against writing invalid data, similar to the
# previous SQLite implementation. It provides flexibility while ensuring consistency.
# 'valid' and 'untested' are special statuses not present in ErrorReason.
VALID_STATUSES = {reason.value for reason in ErrorReason} | {'valid', 'untested'}


# This constant defines the entire database schema using PostgreSQL syntax.
DB_SCHEMA = """
-- Table 1: Provider directory (heart of our multi-provider system)
CREATE TABLE IF NOT EXISTS providers (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

-- Table 2: The proxy servers themselves. A global pool of proxies.
CREATE TABLE IF NOT EXISTS proxies (
    id SERIAL PRIMARY KEY,
    address TEXT UNIQUE NOT NULL -- e.g., "socks5://user:pass@host:port"
);

-- Table 3: Health status of a proxy FOR A SPECIFIC PROVIDER.
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

-- Table 4: API keys. Now with an 'is_dead' flag.
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    key_value TEXT NOT NULL,
    is_dead BOOLEAN NOT NULL DEFAULT FALSE, -- Flag for permanently invalid keys
    UNIQUE (provider_id, key_value),
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);

-- Table 5: Health status for each key-model pair.
CREATE TABLE IF NOT EXISTS key_model_status (
    key_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL, -- e.g., 'valid', 'no_quota', 'invalid_key'
    last_checked TIMESTAMPTZ,
    next_check_time TIMESTAMPTZ NOT NULL,
    status_code INTEGER,
    response_time REAL,
    error_message TEXT,
    PRIMARY KEY (key_id, model_name),
    FOREIGN KEY (key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

-- Indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_api_keys_provider_id ON api_keys(provider_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_is_dead ON api_keys(is_dead);
CREATE INDEX IF NOT EXISTS idx_key_model_status_next_check_time ON key_model_status(next_check_time);
CREATE INDEX IF NOT EXISTS idx_key_model_status_status ON key_model_status(status);
CREATE INDEX IF NOT EXISTS idx_proxy_status_next_check_time ON provider_proxy_status(next_check_time);
CREATE INDEX IF NOT EXISTS idx_proxy_status_status ON provider_proxy_status(status);
"""

# --- Component 1: Connection Management ---

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
    Manages data access for the 'providers' table.
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
    def __init__(self, pool: Pool, config: Config):
        self._pool = pool
        self._config = config

    async def sync(self, provider_name: str, keys_from_file: Set[str], provider_id: int, provider_models: List[str]):
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
                            models_to_add.append((key_id, model_name, 'untested', initial_check_time))
                
                if models_to_add:
                    await conn.copy_records_to_table('key_model_status', records=models_to_add, columns=['key_id', 'model_name', 'status', 'next_check_time'])
                    logger.info(f"SYNC: Added {len(models_to_add)} new model status records for provider '{provider_name}'.")

    async def get_keys_to_check(self) -> List[Dict[str, Any]]:
        query = """
        SELECT
            k.id AS key_id,
            k.key_value,
            p.name AS provider_name,
            s.model_name AS model_name
        FROM api_keys AS k
        JOIN key_model_status AS s ON k.id = s.key_id
        JOIN providers AS p ON k.provider_id = p.id
        WHERE k.is_dead = FALSE AND s.next_check_time <= NOW() AT TIME ZONE 'utc'
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        results = []
        checked_keys_for_shared_providers = set()
        
        for row in rows:
            provider_name = row['provider_name']
            provider_conf = self._config.providers.get(provider_name)

            if provider_conf and provider_conf.shared_key_status:
                key_id = row['key_id']
                if key_id in checked_keys_for_shared_providers:
                    continue
                
                if row['model_name'] == provider_conf.default_model:
                    results.append(dict(row))
                    checked_keys_for_shared_providers.add(key_id)
            else:
                results.append(dict(row))
        return results

    async def update_status(self, key_id: int, model_name: str, provider_name: str, result: CheckResult, next_check_time: datetime):
        status_str = 'valid' if result.ok else result.error_reason.value
        
        # --- ADDED: Application-level data integrity check ---
        # This assert ensures that we never attempt to write an unsupported status string,
        # preventing data corruption and immediately highlighting logical errors in the calling code.
        assert status_str in VALID_STATUSES, f"Attempted to write invalid status '{status_str}' to the database!"

        provider_config = self._config.providers.get(provider_name)
        
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if provider_config and provider_config.shared_key_status:
                    await conn.execute(
                        """
                        UPDATE key_model_status
                        SET status = $1, last_checked = NOW() AT TIME ZONE 'utc', next_check_time = $2,
                            status_code = $3, response_time = $4, error_message = $5
                        WHERE key_id = $6
                        """,
                        status_str, next_check_time, result.status_code, result.response_time,
                        result.message[:1000], key_id
                    )
                    logger.info(f"PROPAGATED status for key ID {key_id} to '{status_str}' for all its models.")
                else:
                    await conn.execute(
                        """
                        UPDATE key_model_status
                        SET status = $1, last_checked = NOW() AT TIME ZONE 'utc', next_check_time = $2,
                            status_code = $3, response_time = $4, error_message = $5
                        WHERE key_id = $6 AND model_name = $7
                        """,
                        status_str, next_check_time, result.status_code, result.response_time,
                        result.message[:1000], key_id, model_name
                    )

                if result.error_reason == ErrorReason.INVALID_KEY:
                    await conn.execute("UPDATE api_keys SET is_dead = TRUE WHERE id = $1", key_id)
                    logger.info(f"FLAGGED: Key ID {key_id} marked as dead due to invalid key error.")

    async def get_available_key(self, provider_name: str, model_name: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT
                k.id AS key_id,
                k.key_value
            FROM api_keys AS k
            JOIN key_model_status AS s ON k.id = s.key_id
            JOIN providers AS p ON k.provider_id = p.id
            WHERE k.is_dead = FALSE AND p.name = $1 AND s.model_name = $2 AND s.status = 'valid'
            ORDER BY RANDOM()
            LIMIT 1
            """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, provider_name, model_name)
        return dict(row) if row else None

    async def get_status_summary(self) -> List[Dict[str, Any]]:
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
         pass


# --- Component 4: Facade ---

class DatabaseManager:
    """
    A facade class that provides a single point of access to all repository objects.
    """
    def __init__(self, config: Config):
        pool = get_pool()
        self.providers = ProviderRepository(pool)
        self.keys = KeyRepository(pool, config)
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
        This acts as a health check during application startup.

        Returns:
            True if the connection is successful, False otherwise.
        """
        try:
            pool = get_pool()
            # Acquire a connection from the pool. This checks network, auth, etc.
            async with pool.acquire() as conn:
                # Execute the simplest and fastest possible query.
                result = await conn.fetchval('SELECT 1')
                # If the query returns 1, the connection is healthy.
                return result == 1
        except Exception as e:
            # Catch any exception during connection or query execution.
            logger.error(f"Database connection check failed: {e}")
            return False

    async def run_amnesty(self, provider_name: Optional[str] = None):
        """Grants amnesty to all 'dead' keys, giving them a second chance."""
        pool = get_pool()
        async with pool.acquire() as conn:
            if provider_name:
                provider_id_row = await conn.fetchrow("SELECT id FROM providers WHERE name = $1", provider_name)
                if provider_id_row:
                    provider_id = provider_id_row['id']
                    status = await conn.execute("UPDATE api_keys SET is_dead = FALSE WHERE is_dead = TRUE AND provider_id = $1", provider_id)
                    logger.info(f"MAINTENANCE: Amnesty for '{provider_name}'. {status.split()[-1]} keys reset.")
                else:
                    logger.warning(f"MAINTENANCE: Provider '{provider_name}' not found for amnesty.")
            else:
                status = await conn.execute("UPDATE api_keys SET is_dead = FALSE WHERE is_dead = TRUE")
                logger.info(f"MAINTENANCE: Global amnesty for all 'dead' keys. {status.split()[-1]} keys reset.")

    async def run_vacuum(self):
        """Executes the VACUUM command to optimize the database."""
        pool = get_pool()
        async with pool.acquire() as conn:
            logger.info("MAINTENANCE: Starting database VACUUM operation...")
            await conn.execute("VACUUM;")
            logger.info("MAINTENANCE: Database VACUUM completed successfully.")
