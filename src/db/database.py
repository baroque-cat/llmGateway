# src/db/database.py

import sqlite3
import logging
from datetime import datetime
from typing import List, Set, Dict, Any, Optional

from src.core.enums import ErrorReason

# --- Module-level logger setup ---
# All database operations will log through this logger.
# Configuration (level, format, destination) is handled at the application entry point.
logger = logging.getLogger(__name__)

# --- Data Integrity Contract ---
# Create a set of all valid string values for the status field.
# This acts as a programmatic guard against writing invalid data.
# 'VALID' and 'UNTESTED' are special statuses not present in ErrorReason.
VALID_STATUSES = {reason.value for reason in ErrorReason} | {'VALID', 'UNTESTED'}


# This constant defines the entire database schema in one place.
# It makes the schema version-controllable and easy to read.
# ON DELETE CASCADE is used to ensure data integrity when parent records are removed.
DB_SCHEMA = """
-- Table 1: Provider directory (heart of our multi-provider system)
CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

-- Table 2: The proxy servers themselves. A global pool of proxies.
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT UNIQUE NOT NULL -- e.g., "socks5://user:pass@host:port"
);

-- Table 3: Health status of a proxy FOR A SPECIFIC PROVIDER.
-- This is the key table for the "stealth mode". It links a proxy from the global
-- pool to a specific provider and tracks its health in that context.
CREATE TABLE IF NOT EXISTS provider_proxy_status (
    proxy_id INTEGER NOT NULL,
    provider_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_checked TIMESTAMP,
    next_check_time TIMESTAMP NOT NULL,
    error_message TEXT,
    PRIMARY KEY (proxy_id, provider_id),
    FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE,
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);

-- Table 4: API keys. Now with an 'is_dead' flag.
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL,
    key_value TEXT NOT NULL,
    is_dead BOOLEAN NOT NULL DEFAULT FALSE, -- Flag for permanently invalid keys for this provider
    UNIQUE (provider_id, key_value),
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);

-- Table 5: Health status for each key-model pair.
CREATE TABLE IF NOT EXISTS key_model_status (
    key_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL, -- e.g., 'VALID', 'NO_QUOTA', 'INVALID_KEY'
    last_checked TIMESTAMP,
    next_check_time TIMESTAMP NOT NULL,
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

def get_db_connection(db_path: str) -> Optional[sqlite3.Connection]:
    """
    Establishes a connection to the SQLite database.

    Args:
        db_path: The file path to the SQLite database.

    Returns:
        A connection object or None if connection fails.
    """
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Allows accessing columns by name
        conn.execute("PRAGMA foreign_keys = ON;") # Enforce foreign key constraints
        return conn
    except sqlite3.Error as e:
        logger.critical(f"Failed to connect to database at '{db_path}': {e}", exc_info=True)
        return None

def initialize_database(db_path: str):
    """
    Initializes the database by creating all necessary tables from the schema.

    Args:
        db_path: The file path to the SQLite database.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return

    try:
        with conn:
            conn.executescript(DB_SCHEMA)
        logger.info("Database initialized successfully.")
    except sqlite3.Error as e:
        logger.critical(f"Failed to initialize database schema: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# --- Synchronization Functions ---

def sync_providers(db_path: str, provider_names_from_config: List[str]):
    """
    Synchronizes the providers table with the list of providers from the config file.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return

    try:
        with conn:
            cursor = conn.execute("SELECT name FROM providers")
            providers_in_db = {row['name'] for row in cursor.fetchall()}
            
            new_providers = set(provider_names_from_config) - providers_in_db
            
            if new_providers:
                to_insert = [(name,) for name in new_providers]
                conn.executemany("INSERT INTO providers (name) VALUES (?)", to_insert)
                logger.info(f"SYNC: Added {len(new_providers)} new providers to the database: {new_providers}")

    except sqlite3.Error as e:
        logger.error(f"Failed to sync providers: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def sync_keys_for_provider(db_path: str, provider_name: str, keys_from_file: Set[str], provider_models: List[str]):
    """
    Synchronizes the api_keys and key_model_status tables for a specific provider.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return

    try:
        with conn:
            # 1. Get provider ID
            cursor = conn.execute("SELECT id FROM providers WHERE name = ?", (provider_name,))
            provider_row = cursor.fetchone()
            if not provider_row:
                logger.error(f"SYNC: Provider '{provider_name}' not found. Run provider sync first.")
                return
            provider_id = provider_row['id']

            # 2. Get keys for this provider from DB
            cursor = conn.execute("SELECT id, key_value FROM api_keys WHERE provider_id = ?", (provider_id,))
            keys_in_db = {row['key_value']: row['id'] for row in cursor.fetchall()}
            db_key_values = set(keys_in_db.keys())

            # 3. Add new keys to api_keys table
            new_keys_to_add = keys_from_file - db_key_values
            if new_keys_to_add:
                to_insert = [(provider_id, key) for key in new_keys_to_add]
                conn.executemany("INSERT INTO api_keys (provider_id, key_value) VALUES (?, ?)", to_insert)
                logger.info(f"SYNC: Added {len(new_keys_to_add)} new keys for provider '{provider_name}'.")
                cursor = conn.execute("SELECT id, key_value FROM api_keys WHERE provider_id = ?", (provider_id,))
                keys_in_db = {row['key_value']: row['id'] for row in cursor.fetchall()}

            # 4. Remove old keys from api_keys table
            keys_to_remove = db_key_values - keys_from_file
            if keys_to_remove:
                ids_to_remove = [keys_in_db[val] for val in keys_to_remove]
                conn.executemany("DELETE FROM api_keys WHERE id = ?", [(id,) for id in ids_to_remove])
                logger.info(f"SYNC: Removed {len(keys_to_remove)} obsolete keys for provider '{provider_name}'.")

            # 5. Sync key_model_status table
            cursor = conn.execute("SELECT id FROM api_keys WHERE provider_id = ?", (provider_id,))
            current_key_ids = {row['id'] for row in cursor.fetchall()}

            if not current_key_ids:
                return
            
            placeholders = ','.join('?' for _ in current_key_ids)
            cursor = conn.execute(f"SELECT key_id, model_name FROM key_model_status WHERE key_id IN ({placeholders})", tuple(current_key_ids))
            model_statuses_in_db = {(row['key_id'], row['model_name']) for row in cursor.fetchall()}
            
            models_to_add = []
            initial_check_time = datetime.utcnow().isoformat()
            for key_id in current_key_ids:
                for model_name in provider_models:
                    if (key_id, model_name) not in model_statuses_in_db:
                        models_to_add.append((key_id, model_name, 'UNTESTED', initial_check_time))
            
            if models_to_add:
                conn.executemany(
                    "INSERT INTO key_model_status (key_id, model_name, status, next_check_time) VALUES (?, ?, ?, ?)",
                    models_to_add
                )
                logger.info(f"SYNC: Added {len(models_to_add)} new model status records for provider '{provider_name}'.")

    except sqlite3.Error as e:
        logger.error(f"Failed to sync keys for provider '{provider_name}': {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


def sync_proxies_for_provider(db_path: str, provider_name: str, proxies_from_file: Set[str]):
    """
    Synchronizes the proxies and provider_proxy_status tables for a specific provider.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return

    try:
        with conn:
            # 1. Get provider ID
            cursor = conn.execute("SELECT id FROM providers WHERE name = ?", (provider_name,))
            provider_row = cursor.fetchone()
            if not provider_row:
                logger.error(f"SYNC: Provider '{provider_name}' not found for proxy sync.")
                return
            provider_id = provider_row['id']

            # 2. Sync global `proxies` table
            cursor = conn.execute("SELECT id, address FROM proxies")
            proxies_in_db = {row['address']: row['id'] for row in cursor.fetchall()}
            new_proxies = proxies_from_file - set(proxies_in_db.keys())

            if new_proxies:
                conn.executemany("INSERT INTO proxies (address) VALUES (?)", [(p,) for p in new_proxies])
                logger.info(f"SYNC: Added {len(new_proxies)} new proxies to the global pool.")
                # Refresh the mapping
                cursor = conn.execute("SELECT id, address FROM proxies")
                proxies_in_db = {row['address']: row['id'] for row in cursor.fetchall()}

            # 3. Sync `provider_proxy_status` table
            proxy_ids_from_file = {proxies_in_db[addr] for addr in proxies_from_file if addr in proxies_in_db}

            cursor = conn.execute("SELECT proxy_id FROM provider_proxy_status WHERE provider_id = ?", (provider_id,))
            linked_proxy_ids_in_db = {row['proxy_id'] for row in cursor.fetchall()}

            # Add new links
            ids_to_link = proxy_ids_from_file - linked_proxy_ids_in_db
            if ids_to_link:
                initial_check_time = datetime.utcnow().isoformat()
                to_insert = [(pid, provider_id, 'UNTESTED', initial_check_time) for pid in ids_to_link]
                conn.executemany(
                    "INSERT INTO provider_proxy_status (proxy_id, provider_id, status, next_check_time) VALUES (?, ?, ?, ?)",
                    to_insert
                )
                logger.info(f"SYNC: Linked {len(ids_to_link)} new proxies to provider '{provider_name}'.")
            
            # Remove old links
            ids_to_unlink = linked_proxy_ids_in_db - proxy_ids_from_file
            if ids_to_unlink:
                conn.executemany("DELETE FROM provider_proxy_status WHERE provider_id = ? AND proxy_id = ?", 
                                 [(provider_id, pid) for pid in ids_to_unlink])
                logger.info(f"SYNC: Unlinked {len(ids_to_unlink)} obsolete proxies from provider '{provider_name}'.")

    except sqlite3.Error as e:
        logger.error(f"Failed to sync proxies for provider '{provider_name}': {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# --- Operational Functions ---

def update_key_model_status(db_path: str, key_id: int, model_name: str, status: str, next_check_time: datetime, status_code: Optional[int], response_time: float, error_message: str):
    """
    Updates the status of a key-model pair based on pre-computed values.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return

    assert status in VALID_STATUSES, f"Attempted to write invalid status '{status}' to the database!"
            
    try:
        with conn:
            conn.execute(
                """
                UPDATE key_model_status
                SET status = ?, last_checked = ?, next_check_time = ?,
                    status_code = ?, response_time = ?, error_message = ?
                WHERE key_id = ? AND model_name = ?
                """,
                (
                    status,
                    datetime.utcnow().isoformat(),
                    next_check_time.isoformat(),
                    status_code,
                    response_time,
                    error_message[:1000],
                    key_id,
                    model_name
                )
            )

            if status == ErrorReason.INVALID_KEY.value:
                conn.execute("UPDATE api_keys SET is_dead = TRUE WHERE id = ?", (key_id,))
                logger.info(f"FLAGGED: Key ID {key_id} marked as dead due to invalid key error.")

    except sqlite3.Error as e:
        logger.error(f"Failed to update status for key_id {key_id}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


def get_keys_to_check(db_path: str) -> List[Dict[str, Any]]:
    """
    Retrieves all key-model pairs that are due for a health check, excluding dead keys.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return []

    results = []
    try:
        now_str = datetime.utcnow().isoformat()
        cursor = conn.execute(
            """
            SELECT
                k.id AS key_id,
                k.key_value,
                p.name AS provider_name,
                s.model_name AS model_name
            FROM api_keys AS k
            JOIN key_model_status AS s ON k.id = s.key_id
            JOIN providers AS p ON k.provider_id = p.id
            WHERE k.is_dead = FALSE AND s.next_check_time <= ?
            """,
            (now_str,)
        )
        results = [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Failed to get keys to check: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return results

def get_available_key(db_path: str, provider_name: str, model_name: str) -> Optional[Dict[str, Any]]:
    """
    Finds a random, available (VALID) key for a given provider and model.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return None

    result = None
    try:
        cursor = conn.execute(
            """
            SELECT
                k.id AS key_id,
                k.key_value
            FROM api_keys AS k
            JOIN key_model_status AS s ON k.id = s.key_id
            JOIN providers AS p ON k.provider_id = p.id
            WHERE k.is_dead = FALSE AND p.name = ? AND s.model_name = ? AND s.status = 'VALID'
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (provider_name, model_name)
        )
        row = cursor.fetchone()
        if row:
            result = dict(row)
    except sqlite3.Error as e:
        logger.error(f"Failed to get available key for '{provider_name}' - '{model_name}': {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return result

def get_status_summary(db_path: str) -> List[Dict[str, Any]]:
    """
    Retrieves an aggregated summary of key statuses grouped by provider, model, and status.
    This function is designed to be used by the statistics logger service.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return []

    results = []
    try:
        cursor = conn.execute(
            """
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
        )
        results = [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Failed to get status summary from database: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return results

# --- Maintenance Functions ---

def amnesty_dead_keys(db_path: str, provider_name: Optional[str] = None):
    """
    Resets the 'is_dead' flag for keys, giving them a second chance to be re-validated.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return
    
    try:
        with conn:
            if provider_name:
                cursor = conn.execute("SELECT id FROM providers WHERE name = ?", (provider_name,))
                provider_row = cursor.fetchone()
                if provider_row:
                    provider_id = provider_row['id']
                    cursor = conn.execute("UPDATE api_keys SET is_dead = FALSE WHERE is_dead = TRUE AND provider_id = ?", (provider_id,))
                    logger.info(f"MAINTENANCE: Amnesty granted for 'dead' keys of provider '{provider_name}'. {cursor.rowcount} keys reset.")
                else:
                    logger.warning(f"MAINTENANCE: Provider '{provider_name}' not found for amnesty.")
            else:
                cursor = conn.execute("UPDATE api_keys SET is_dead = FALSE WHERE is_dead = TRUE")
                logger.info(f"MAINTENANCE: Global amnesty granted for all 'dead' keys. {cursor.rowcount} keys reset.")

    except sqlite3.Error as e:
        logger.error(f"Failed during key amnesty: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def vacuum_database(db_path: str):
    """
    Executes the VACUUM command to rebuild and optimize the database file.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return
    
    try:
        logger.info("MAINTENANCE: Starting database VACUUM operation...")
        conn.execute("VACUUM;")
        logger.info("MAINTENANCE: Database VACUUM completed successfully.")
    except sqlite3.Error as e:
        logger.error(f"VACUUM operation failed: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

