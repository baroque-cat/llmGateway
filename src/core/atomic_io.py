# src/core/atomic_io.py

"""
Atomic I/O utilities — stdlib-only primitives for safe file writes.

This module provides a single pure function for writing NDJSON files atomically.
It depends only on the Python standard library and is fully synchronous by design.
"""

import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)


def write_atomic_ndjson(path: str, records: list[dict[str, Any]]) -> None:
    """Write a list of records to a newline-delimited JSON file atomically.

    The file is written to a temporary file in the same directory as the target,
    flushed to disk, and then atomically renamed to the target path.  This
    guarantees that any reader of **path** sees either the old file (if it
    existed) or the complete new file — never a partial write.

    **Atomicity guarantee**:
        Uses ``tempfile.NamedTemporaryFile`` + ``os.fsync`` + ``os.replace``.
        On POSIX systems, ``os.replace`` is an atomic rename that replaces
        the target file in a single filesystem operation.

    Args:
        path: Absolute or relative path to the target NDJSON file.
        records: List of dicts to serialize as JSON lines (one dict per line).
            An empty list results in an empty file.

    Raises:
        OSError: If the file cannot be written or the directory cannot be
            created (permission errors, disk full, etc.).
    """
    dirname = os.path.dirname(os.path.abspath(path))

    # Ensure the target directory exists.
    os.makedirs(dirname, exist_ok=True)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=dirname,
        delete=False,
        suffix=".tmp",
        encoding="utf-8",
    )
    try:
        for record in records:
            json_line = json.dumps(record, ensure_ascii=False)
            tmp.write(json_line + "\n")

        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path: str = tmp.name
        tmp.close()

        os.replace(src=tmp_path, dst=path)

    except Exception:
        # On any error, clean up the temporary file.
        try:
            tmp.close()
        except OSError:
            pass
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
