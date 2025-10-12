# src/db/database.py

import sqlite3
import traceback
from datetime import datetime, timedelta
from typing import List, Set, Dict, Any, Optional

from src.core.models import CheckResult
from src.core.enums import ErrorReason

# --- Data Integrity Contract ---
# Create a set of all valid string values for the status field.
# This acts as a programmatic guard against writing invalid data.
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

-- Table 2: Lists of proxy servers (allows grouping proxies)
CREATE TABLE IF NOT EXISTS proxy_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    source_path TEXT NOT NULL
);

-- Table 3: The proxy servers themselves
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL,
    address TEXT UNIQUE NOT NULL,
    FOREIGN KEY (list_id) REFERENCES proxy_lists(id) ON DELETE CASCADE
);

-- Table 4: Health status of a proxy FOR A SPECIFIC PROVIDER
-- This is the key table for the "masking mode".
CREATE TABLE IF NOT EXISTS proxy_status (
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

-- Table 5: API keys. Now with an 'is_dead' flag.
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL,
    key_value TEXT NOT NULL,
    is_dead BOOLEAN NOT NULL DEFAULT FALSE, -- Flag for permanently invalid keys for this provider
    UNIQUE (provider_id, key_value),
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);

-- Table 6: NEW - Health status for each key-model pair.
-- Replaces the old 'key_status' table.
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
        return conn
    except sqlite3.Error:
        print("--- DATABASE ERROR: Failed to connect to database ---")
        traceback.print_exc()
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
        print("Database initialized successfully.")
    except sqlite3.Error:
        print("--- DATABASE ERROR: Failed to initialize database ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

# --- Synchronization Functions ---

def sync_providers(db_path: str, provider_names_from_config: List[str]):
    """
    Synchronizes the providers table with the list of providers from the config file.

    Args:
        db_path: Path to the database file.
        provider_names_from_config: A list of provider names defined in the config.
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
                print(f"SYNC: Added {len(new_providers)} new providers to the database: {new_providers}")

    except sqlite3.Error:
        print("--- DATABASE ERROR: Failed to sync providers ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

def sync_keys_for_provider(db_path: str, provider_name: str, keys_from_file: Set[str], provider_models: List[str]):
    """
    Synchronizes the api_keys and key_model_status tables for a specific provider.

    Args:
        db_path: Path to the database file.
        provider_name: The name of the provider to sync keys for.
        keys_from_file: A set of key strings read from the provider's key files.
        provider_models: A list of model names supported by this provider from config.
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
                print(f"SYNC ERROR: Provider '{provider_name}' not found. Run provider sync first.")
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
                print(f"SYNC: Added {len(new_keys_to_add)} new keys for provider '{provider_name}'.")
                # Refresh keys_in_db to get the new IDs
                cursor = conn.execute("SELECT id, key_value FROM api_keys WHERE provider_id = ?", (provider_id,))
                keys_in_db = {row['key_value']: row['id'] for row in cursor.fetchall()}

            # 4. Remove old keys from api_keys table
            keys_to_remove = db_key_values - keys_from_file
            if keys_to_remove:
                ids_to_remove = [keys_in_db[val] for val in keys_to_remove]
                conn.executemany("DELETE FROM api_keys WHERE id = ?", [(id,) for id in ids_to_remove])
                print(f"SYNC: Removed {len(keys_to_remove)} obsolete keys for provider '{provider_name}'.")

            # 5. Sync key_model_status table for all current keys of this provider
            cursor = conn.execute("SELECT id FROM api_keys WHERE provider_id = ?", (provider_id,))
            current_key_ids = {row['id'] for row in cursor.fetchall()}

            cursor = conn.execute("SELECT key_id, model_name FROM key_model_status WHERE key_id IN ({})".format(','.join('?'*len(current_key_ids)) if current_key_ids else '0'), (*current_key_ids,))
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
                print(f"SYNC: Added {len(models_to_add)} new model status records for provider '{provider_name}'.")

    except sqlite3.Error:
        print(f"--- DATABASE ERROR: Failed to sync keys for provider '{provider_name}' ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

# --- Operational Functions ---

def update_key_model_status(db_path: str, key_id: int, model_name: str, result: CheckResult):
    """
    Updates the status of a key-model pair and potentially marks the key as dead.

    Args:
        db_path: Path to the database file.
        key_id: The ID of the key to update.
        model_name: The name of the model that was tested.
        result: The CheckResult object from the provider's check method.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return
        
    now = datetime.utcnow()
    next_check_time = now

    if result.ok:
        status = 'VALID'
        next_check_time = now + timedelta(hours=12)
    else:
        status = result.error_reason.value
        if result.error_reason.is_retryable():
            next_check_time = now + timedelta(minutes=10)
        elif result.error_reason in (ErrorReason.INVALID_KEY, ErrorReason.NO_ACCESS):
            next_check_time = now + timedelta(days=10)
        else:
            next_check_time = now + timedelta(days=1)
    
    # Assert that the status we are about to write is a valid, known status.
    # This prevents data corruption from future code changes.
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
                    now.isoformat(),
                    next_check_time.isoformat(),
                    result.status_code,
                    result.response_time,
                    result.message[:1000],
                    key_id,
                    model_name
                )
            )

            # If the key is confirmed invalid, mark it as dead for this provider.
            if result.error_reason == ErrorReason.INVALID_KEY:
                conn.execute("UPDATE api_keys SET is_dead = TRUE WHERE id = ?", (key_id,))
                print(f"FLAGGED: Key ID {key_id} marked as dead due to invalid key error.")

    except sqlite3.Error:
        print(f"--- DATABASE ERROR: Failed to update status for key_id {key_id} ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

def get_keys_to_check(db_path: str) -> List[Dict[str, Any]]:
    """
    Retrieves all key-model pairs that are due for a health check, excluding dead keys.

    Returns:
        A list of dictionaries, each containing key, model, and provider info.
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
    except sqlite3.Error:
        print("--- DATABASE ERROR: Failed to get keys to check ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()
    return results

def get_available_key(db_path: str, provider_name: str, model_name: str) -> Optional[Dict[str, Any]]:
    """
    Finds a random, available (VALID) key for a given provider and model.

    Args:
        provider_name: The name of the provider.
        model_name: The name of the model requested.

    Returns:
        A dictionary with key info, or None if no valid key is found.
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
    except sqlite3.Error:
        print(f"--- DATABASE ERROR: Failed to get available key for '{provider_name}' - '{model_name}' ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()
    return result

# --- Maintenance Functions ---

def amnesty_dead_keys(db_path: str, provider_name: Optional[str] = None):
    """
    Resets the 'is_dead' flag for all keys, or only for a specific provider.
    This gives "dead" keys a second chance to be re-validated.

    Args:
        db_path: Path to the database file.
        provider_name: (Optional) The name of the provider to run amnesty for.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return
    
    try:
        with conn:
            if provider_name:
                cursor = conn.execute("SELECT id FROM providers WHERE name = ?", (provider_name,))
                provider_id = cursor.fetchone()['id']
                cursor = conn.execute("UPDATE api_keys SET is_dead = FALSE WHERE is_dead = TRUE AND provider_id = ?", (provider_id,))
                print(f"MAINTENANCE: Amnesty granted for 'dead' keys of provider '{provider_name}'. {cursor.rowcount} keys reset.")
            else:
                cursor = conn.execute("UPDATE api_keys SET is_dead = FALSE WHERE is_dead = TRUE")
                print(f"MAINTENANCE: Global amnesty granted for all 'dead' keys. {cursor.rowcount} keys reset.")

    except sqlite3.Error:
        print("--- DATABASE ERROR: Failed during key amnesty ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

def vacuum_database(db_path: str):
    """
    Executes the VACUUM command to rebuild the database file, repacking it into a minimal amount of disk space.

    Args:
        db_path: Path to the database file.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return
    
    try:
        print("MAINTENANCE: Starting database VACUUM operation...")
        conn.execute("VACUUM;")
        print("MAINTENANCE: Database VACUUM completed successfully.")
    except sqlite3.Error:
        print("--- DATABASE ERROR: VACUUM operation failed ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()


# --- Proxy-related Function Stubs ---
# These are kept as stubs for now as per the development plan.

def sync_proxy_lists(db_path: str, proxy_lists_from_config: Dict[str, str]):
    """(STUB) Synchronizes the proxy_lists table with the config."""
    print("TODO: Implement sync_proxy_lists")
    pass

def sync_proxies_for_list(db_path: str, list_name: str, proxies_from_file: Set[str]):
    """(STUB) Synchronizes the proxies table for a specific list."""
    print("TODO: Implement sync_proxies_for_list")
    pass

def update_proxy_status(db_path: str, proxy_id: int, provider_id: int, result: CheckResult):
    """(STUB) Updates the status of a proxy for a specific provider."""
    print("TODO: Implement update_proxy_status")
    pass

def get_proxies_to_check(db_path: str) -> List[Dict[str, Any]]:
    """(STUB) Retrieves proxies that are due for a health check."""
    print("TODO: Implement get_proxies_to_check")
    return []

def get_available_proxy(db_path: str, provider_name: str) -> Optional[Dict[str, Any]]:
    """(STUB) Finds a random, available proxy for a given provider."""
    print("TODO: Implement get_available_proxy")
    return None
