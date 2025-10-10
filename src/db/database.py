# src/db/database.py

import sqlite3
import traceback
from datetime import datetime, timedelta
from typing import List, Set, Dict, Any, Optional

from src.core.models import CheckResult
from src.core.enums import ErrorReason

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

-- Table 5: API keys
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL,
    key_value TEXT NOT NULL,
    UNIQUE (provider_id, key_value),
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);

-- Table 6: Health status of keys
CREATE TABLE IF NOT EXISTS key_status (
    key_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    last_checked TIMESTAMP,
    next_check_time TIMESTAMP NOT NULL,
    status_code INTEGER,
    response_time REAL,
    error_message TEXT,
    FOREIGN KEY (key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);
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
# Justification: These functions form the bridge between the configuration/files
# and the database state. They are designed to be idempotent - running them
# multiple times with the same input will not cause issues.
# I am starting with provider sync as it's the top-level entity.

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
                # Use executemany for efficient batch insertion
                to_insert = [(name,) for name in new_providers]
                conn.executemany("INSERT INTO providers (name) VALUES (?)", to_insert)
                print(f"SYNC: Added {len(new_providers)} new providers to the database: {new_providers}")

    except sqlite3.Error:
        print("--- DATABASE ERROR: Failed to sync providers ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

# Justification: Now, the key synchronization function. This is more complex.
# It needs to get the provider's ID, then compare file keys with DB keys for that specific provider.
# For any new key, it must also create a default "untested" status record in key_status.
# This ensures the key is immediately picked up by the background tester.
# The use of set operations makes this process highly efficient.

def sync_keys_for_provider(db_path: str, provider_name: str, keys_from_file: Set[str]):
    """
    Synchronizes the api_keys and key_status tables for a specific provider.

    Args:
        db_path: Path to the database file.
        provider_name: The name of the provider to sync keys for.
        keys_from_file: A set of key strings read from the provider's key files.
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
                print(f"SYNC ERROR: Provider '{provider_name}' not found in database. Run provider sync first.")
                return
            provider_id = provider_row['id']

            # 2. Get keys for this provider from DB
            cursor = conn.execute("SELECT id, key_value FROM api_keys WHERE provider_id = ?", (provider_id,))
            keys_in_db = {row['key_value']: row['id'] for row in cursor.fetchall()}
            db_key_values = set(keys_in_db.keys())

            # 3. Add new keys
            new_keys_to_add = keys_from_file - db_key_values
            if new_keys_to_add:
                to_insert = [(provider_id, key) for key in new_keys_to_add]
                cursor = conn.executemany("INSERT INTO api_keys (provider_id, key_value) VALUES (?, ?)", to_insert)
                
                # 3.1 For each new key, create an initial status record
                # This is crucial for the key tester to pick them up.
                newly_inserted_ids = [rowid[0] for rowid in cursor.execute(
                    "SELECT id FROM api_keys WHERE provider_id = ? AND key_value IN ({})".format(
                        ','.join('?'*len(new_keys_to_add))
                    ), (provider_id, *new_keys_to_add)
                ).fetchall()]
                
                status_to_insert = []
                initial_check_time = datetime.utcnow().isoformat()
                for key_id in newly_inserted_ids:
                    status_to_insert.append(
                        (key_id, ErrorReason.UNKNOWN.value, initial_check_time)
                    )
                conn.executemany(
                    "INSERT INTO key_status (key_id, status, next_check_time) VALUES (?, ?, ?)",
                    status_to_insert
                )
                print(f"SYNC: Added {len(new_keys_to_add)} new keys for provider '{provider_name}'.")

            # 4. Remove old keys
            keys_to_remove = db_key_values - keys_from_file
            if keys_to_remove:
                ids_to_remove = [keys_in_db[val] for val in keys_to_remove]
                # The ON DELETE CASCADE on key_status will handle cleaning up status records automatically.
                conn.executemany("DELETE FROM api_keys WHERE id = ?", [(id,) for id in ids_to_remove])
                print(f"SYNC: Removed {len(keys_to_remove)} obsolete keys for provider '{provider_name}'.")

    except sqlite3.Error:
        print(f"--- DATABASE ERROR: Failed to sync keys for provider '{provider_name}' ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

# --- Operational Functions ---
# Justification: These functions are the API for the rest of the application.
# `update_key_status` is the most critical. It accepts a rich CheckResult object,
# which is a core part of our new architecture. It contains the logic for scheduling
# the next check based on the error type, abstracting this away from the tester.

def update_key_status(db_path: str, key_id: int, result: CheckResult):
    """
    Updates the status of a key in the database based on a CheckResult.

    Args:
        db_path: Path to the database file.
        key_id: The ID of the key to update.
        result: The CheckResult object from the provider's check method.
    """
    conn = get_db_connection(db_path)
    if not conn:
        return
        
    now = datetime.utcnow()
    next_check_time = now # Default to now

    # This is the adaptive scheduling logic based on the error type.
    if result.ok:
        status = 'VALID' # A simple, human-readable valid status
        next_check_time = now + timedelta(hours=12) # Check healthy keys less often
    else:
        status = result.error_reason.value
        if result.error_reason.is_retryable():
             # Retry transient errors relatively quickly
            next_check_time = now + timedelta(minutes=10)
        elif result.error_reason in (ErrorReason.INVALID_KEY, ErrorReason.NO_ACCESS):
            # Do not re-check invalid keys often
            next_check_time = now + timedelta(days=10)
        else:
             # Other client-side errors can be checked less frequently
            next_check_time = now + timedelta(days=1)
            
    try:
        with conn:
            conn.execute(
                """
                UPDATE key_status
                SET status = ?, last_checked = ?, next_check_time = ?,
                    status_code = ?, response_time = ?, error_message = ?
                WHERE key_id = ?
                """,
                (
                    status,
                    now.isoformat(),
                    next_check_time.isoformat(),
                    result.status_code,
                    result.response_time,
                    result.message[:1000], # Truncate message to avoid large db entries
                    key_id
                )
            )
    except sqlite3.Error:
        print(f"--- DATABASE ERROR: Failed to update status for key_id {key_id} ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

# Justification: These "getter" functions will be used by the background worker and proxy service.
# They are read-only operations. `get_keys_to_check` is simple and efficient,
# finding all keys that are due for a check. `get_available_key` implements the
# strategy of finding a validated, working key for immediate use.

def get_keys_to_check(db_path: str) -> List[Dict[str, Any]]:
    """
    Retrieves all keys that are due for a health check.

    Args:
        db_path: Path to the database file.

    Returns:
        A list of dictionaries, each containing key and provider info.
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
                p.name AS provider_name
            FROM api_keys AS k
            JOIN key_status AS s ON k.id = s.key_id
            JOIN providers AS p ON k.provider_id = p.id
            WHERE s.next_check_time <= ?
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

def get_available_key(db_path: str, provider_name: str) -> Optional[Dict[str, Any]]:
    """
    Finds a random, available (VALID) key for a given provider.

    Args:
        db_path: Path to the database file.
        provider_name: The name of the provider.

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
            JOIN key_status AS s ON k.id = s.key_id
            JOIN providers AS p ON k.provider_id = p.id
            WHERE p.name = ? AND s.status = 'VALID'
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (provider_name,)
        )
        row = cursor.fetchone()
        if row:
            result = dict(row)
    except sqlite3.Error:
        print(f"--- DATABASE ERROR: Failed to get available key for provider '{provider_name}' ---")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()
    return result

# --- Proxy-related Function Stubs ---
# Justification: As per our plan, I am adding stubs for proxy-related functions.
# This makes the database module's API complete from the start, even if the
# implementation will be added in a future step. It reminds us of the work to be done
# and allows other modules to be built against this interface.

def sync_proxy_lists(db_path: str, proxy_lists_from_config: Dict[str, str]):
    """
    (STUB) Synchronizes the proxy_lists table with the config.
    """
    print("TODO: Implement sync_proxy_lists")
    pass

def sync_proxies_for_list(db_path: str, list_name: str, proxies_from_file: Set[str]):
    """
    (STUB) Synchronizes the proxies table for a specific list.
    """
    print("TODO: Implement sync_proxies_for_list")
    pass

def update_proxy_status(db_path: str, proxy_id: int, provider_id: int, result: CheckResult):
    """
    (STUB) Updates the status of a proxy for a specific provider.
    """
    print("TODO: Implement update_proxy_status")
    pass

def get_proxies_to_check(db_path: str) -> List[Dict[str, Any]]:
    """
    (STUB) Retrieves proxies that are due for a health check.
    """
    print("TODO: Implement get_proxies_to_check")
    return []

def get_available_proxy(db_path: str, provider_name: str) -> Optional[Dict[str, Any]]:
    """
    (STUB) Finds a random, available proxy for a given provider.
    """
    print("TODO: Implement get_available_proxy")
    return None

