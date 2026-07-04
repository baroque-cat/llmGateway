"""Gatekeeper test: AST-based static analysis of architectural layer imports.

Verifies that Python imports across ``src/`` subdirectories do not violate
the project's architectural layering constraints.  Each layer has a set of
forbidden import prefixes (e.g. ``config`` must not import from ``db`` or
``services``).  The test parses every ``.py`` file with ``ast.parse()``,
extracts ``Import`` and ``ImportFrom`` nodes, and checks module paths
against forbidden-layer sets.

A small whitelist of architecturally valid exceptions is maintained for
known cross-layer imports that are either:

* Deferred runtime imports inside method bodies (to break circular
  dependencies).
* ``TYPE_CHECKING``-guarded imports (type-only, no runtime cost).
* Facade bridges that intentionally couple two layers (e.g.
  ``ConfigAccessor`` wrapping the config schema).

Coverage map entries #19-#24.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Layer -> forbidden import prefixes.
#
# ``config``    must not depend on ``db`` or ``services``.
# ``db``        must not depend on ``providers`` or ``services``.
# ``metrics``   must not depend on ``services`` or ``providers``.
# ``providers`` must not depend on ``services``.
# ``core``      must not depend on ``config``, ``db``, ``metrics``,
#               ``providers``, or ``services`` (self-references to
#               ``src.core`` are permitted).
_LAYER_FORBIDDEN: dict[str, list[str]] = {
    "config": ["src.db", "src.services"],
    "db": ["src.providers", "src.services"],
    "metrics": ["src.services", "src.providers"],
    "providers": ["src.services"],
    "core": [
        "src.config",
        "src.db",
        "src.metrics",
        "src.providers",
        "src.services",
    ],
}

# Whitelist of architecturally valid cross-layer exceptions.
#
# Keys are file paths relative to the repository root (POSIX style).
# Values are sets of forbidden import module paths that are approved
# exceptions for that file.
#
# Rationale per entry:
#   src/db/database.py -> src.services.key_purger:
#       Deferred runtime import inside ``DatabaseManager.__init__()``
#       to break a circular dependency between the db facade and the
#       key-purger service.
#   src/core/accessor.py -> src.config.schemas:
#       ``ConfigAccessor`` is a Facade that intentionally bridges the
#       config and core layers; it requires the config schema types
#       for its constructor parameter and return-type hints.
#   src/core/http_client_factory.py -> src.config.logging_config:
#       Imports ``get_trace_handler`` to wire per-request httpx trace
#       events into the application logging pipeline.
#   src/core/interfaces.py -> src.db.database:
#       ``TYPE_CHECKING``-guarded import of ``DatabaseManager`` used
#       solely for type annotations; no runtime cost.
#   src/core/probes.py -> src.db.database:
#       ``TYPE_CHECKING``-guarded import of ``DatabaseManager`` used
#       solely for type annotations; no runtime cost.
_WHITELIST: dict[str, set[str]] = {
    "src/db/database.py": {"src.services.key_purger"},
    "src/core/accessor.py": {"src.config.schemas"},
    "src/core/http_client_factory.py": {"src.config.logging_config"},
    "src/core/interfaces.py": {"src.db.database"},
    "src/core/probes.py": {"src.db.database"},
}


def _extract_imports(file_path: Path) -> list[str]:
    """Extract all imported module paths from a Python file using AST.

    Walks the parsed abstract syntax tree and collects module names from
    both ``ast.Import`` nodes (``names[].name``) and ``ast.ImportFrom``
    nodes (``module`` attribute).

    Args:
        file_path: Path to a ``.py`` file on disk.

    Returns:
        List of module path strings (e.g. ``"src.db.repository"``,
        ``"os"``, ``"sys"``).
    """
    source: str = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _is_forbidden(import_path: str, forbidden_prefixes: list[str]) -> bool:
    """Check whether *import_path* matches any forbidden prefix.

    A match is either an exact equality (``"src.db"``) or a dotted-child
    prefix (``"src.db.repository"`` starts with ``"src.db."``).

    Args:
        import_path: The module path string to check.
        forbidden_prefixes: List of forbidden prefix strings.

    Returns:
        True if the import matches a forbidden prefix.
    """
    for prefix in forbidden_prefixes:
        if import_path == prefix or import_path.startswith(prefix + "."):
            return True
    return False


def _scan_layer(layer: str) -> list[tuple[Path, str]]:
    """Scan all ``.py`` files in a ``src/`` layer for forbidden imports.

    Recursively walks the layer directory (including subdirectories such
    as ``impl/`` or ``batching/``), parses each file with ``ast.parse()``,
    and records every import that matches a forbidden prefix.

    Args:
        layer: Subdirectory name under ``src/`` (e.g. ``"config"``,
            ``"db"``).

    Returns:
        List of ``(file_path, forbidden_import)`` tuples for every
        violation found, including whitelisted ones.  Use
        :func:`_filter_whitelisted` to suppress approved exceptions.
    """
    layer_dir: Path = _REPO_ROOT / "src" / layer
    if not layer_dir.is_dir():
        return []
    forbidden_prefixes: list[str] = _LAYER_FORBIDDEN.get(layer, [])
    violations: list[tuple[Path, str]] = []
    for py_file in sorted(layer_dir.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        for imp in _extract_imports(py_file):
            if _is_forbidden(imp, forbidden_prefixes):
                violations.append((py_file, imp))
    return violations


def _to_rel_posix(file_path: Path) -> str:
    """Convert an absolute path to a repo-relative POSIX string.

    Args:
        file_path: Absolute path inside the repository.

    Returns:
        Forward-slash relative path (e.g. ``"src/core/probes.py"``).
    """
    return file_path.relative_to(_REPO_ROOT).as_posix()


def _filter_whitelisted(
    violations: list[tuple[Path, str]],
    whitelist: dict[str, set[str]] | None = None,
) -> list[tuple[Path, str]]:
    """Remove whitelisted violations from a violations list.

    A violation is suppressed when the file's relative path is a key in
    the *whitelist* dict and the forbidden import string is present in
    the corresponding set.

    Args:
        violations: Raw violations from :func:`_scan_layer`.
        whitelist: Optional whitelist override.  Defaults to the
            module-level :data:`_WHITELIST`.

    Returns:
        Filtered list of violations with approved exceptions removed.
    """
    wl: dict[str, set[str]] = whitelist if whitelist is not None else _WHITELIST
    filtered: list[tuple[Path, str]] = []
    for file_path, imp in violations:
        rel: str = _to_rel_posix(file_path)
        if imp in wl.get(rel, set()):
            continue
        filtered.append((file_path, imp))
    return filtered


# ── #19: config layer must not import db or services ───────────────────────


def test_config_layer_no_db_or_services_imports() -> None:
    """Verify ``src/config/`` imports neither ``src.db`` nor ``src.services``.

    Parses every ``.py`` file under ``src/config/`` with ``ast.parse()``
    and asserts that no import starts with ``src.db`` or ``src.services``
    after suppressing whitelisted exceptions.
    """
    violations = _filter_whitelisted(_scan_layer("config"))
    assert not violations, "Forbidden imports in config layer:\n" + "\n".join(
        f"  {p}: {imp}" for p, imp in violations
    )


# ── #20: db layer must not import providers or services ────────────────────


def test_db_layer_no_providers_or_services_imports() -> None:
    """Verify ``src/db/`` imports neither ``src.providers`` nor ``src.services``.

    Parses every ``.py`` file under ``src/db/`` with ``ast.parse()``
    and asserts that no import starts with ``src.providers`` or
    ``src.services`` after suppressing whitelisted exceptions.
    """
    violations = _filter_whitelisted(_scan_layer("db"))
    assert not violations, "Forbidden imports in db layer:\n" + "\n".join(
        f"  {p}: {imp}" for p, imp in violations
    )


# ── #21: metrics layer must not import services or providers ───────────────


def test_metrics_layer_no_services_or_providers_imports() -> None:
    """Verify ``src/metrics/`` imports neither ``src.services`` nor ``src.providers``.

    Parses every ``.py`` file under ``src/metrics/`` with ``ast.parse()``
    and asserts that no import starts with ``src.services`` or
    ``src.providers`` after suppressing whitelisted exceptions.
    """
    violations = _filter_whitelisted(_scan_layer("metrics"))
    assert not violations, "Forbidden imports in metrics layer:\n" + "\n".join(
        f"  {p}: {imp}" for p, imp in violations
    )


# ── #22: providers layer must not import services ──────────────────────────


def test_providers_layer_no_services_imports() -> None:
    """Verify ``src/providers/`` (including ``impl/``) does not import ``src.services``.

    Recursively parses every ``.py`` file under ``src/providers/`` with
    ``ast.parse()`` and asserts that no import starts with
    ``src.services`` after suppressing whitelisted exceptions.
    """
    violations = _filter_whitelisted(_scan_layer("providers"))
    assert not violations, "Forbidden imports in providers layer:\n" + "\n".join(
        f"  {p}: {imp}" for p, imp in violations
    )


# ── #23: core layer must not import forbidden layers ───────────────────────


def test_core_layer_no_forbidden_layer_dependencies() -> None:
    """Verify ``src/core/`` (including ``batching/``) has no forbidden dependencies.

    Recursively parses every ``.py`` file under ``src/core/`` with
    ``ast.parse()`` and asserts that no import starts with
    ``src.config``, ``src.db``, ``src.metrics``, ``src.providers``, or
    ``src.services`` after suppressing whitelisted exceptions.

    Self-references to ``src.core`` are permitted and not checked.
    """
    violations = _filter_whitelisted(_scan_layer("core"))
    assert not violations, "Forbidden imports in core layer:\n" + "\n".join(
        f"  {p}: {imp}" for p, imp in violations
    )


# ── #24: well-known exceptions are whitelisted ─────────────────────────────


def test_well_known_exceptions_are_whitelisted() -> None:
    """Verify the whitelist mechanism suppresses approved cross-layer imports.

    Defines a small whitelist dict and confirms that:

    1. The whitelist is non-empty and documented.
    2. Violations matching a whitelist entry are suppressed by
       :func:`_filter_whitelisted`.
    3. Violations not in the whitelist are retained.
    4. The real-world exceptions present in the codebase are correctly
       suppressed by the module-level :data:`_WHITELIST`.
    """
    # --- 1. Whitelist is non-empty and documented ---
    assert len(_WHITELIST) > 0, "Whitelist must contain at least one entry"
    # The module docstring documents each whitelist entry's rationale.
    assert (
        __doc__ is not None and "whitelist" in __doc__.lower()
    ), "Module docstring must document the whitelist rationale"

    # --- 2. Whitelisted violations are suppressed ---
    test_whitelist: dict[str, set[str]] = {
        "src/core/probes.py": {"src.db.database"},
    }
    sample_violations: list[tuple[Path, str]] = [
        (_REPO_ROOT / "src" / "core" / "probes.py", "src.db.database"),
        (_REPO_ROOT / "src" / "core" / "probes.py", "src.services.gateway"),
    ]
    filtered = _filter_whitelisted(sample_violations, whitelist=test_whitelist)
    # The whitelisted import is removed; the non-whitelisted one remains.
    assert (
        len(filtered) == 1
    ), f"Expected 1 remaining violation after whitelist filter, got {filtered}"
    assert (
        filtered[0][1] == "src.services.gateway"
    ), f"Expected 'src.services.gateway' to remain, got {filtered[0][1]}"

    # --- 3. An empty whitelist retains all violations ---
    empty_filtered = _filter_whitelisted(sample_violations, whitelist={})
    assert (
        len(empty_filtered) == 2
    ), f"Empty whitelist should retain all violations, got {empty_filtered}"

    # --- 4. Real-world exceptions are suppressed by the module whitelist ---
    # Collect raw violations across all layers and confirm that every
    # whitelisted entry actually corresponds to a real violation in the
    # codebase (i.e. the whitelist is not stale).
    all_raw: list[tuple[Path, str]] = []
    for layer_name in _LAYER_FORBIDDEN:
        all_raw.extend(_scan_layer(layer_name))
    all_filtered = _filter_whitelisted(all_raw)

    # Every whitelist entry must match at least one raw violation.
    raw_rel_map: dict[str, set[str]] = {}
    for file_path, imp in all_raw:
        raw_rel_map.setdefault(_to_rel_posix(file_path), set()).add(imp)
    for wl_path, wl_imports in _WHITELIST.items():
        assert wl_path in raw_rel_map, (
            f"Whitelist entry '{wl_path}' does not match any scanned file; "
            "the whitelist may be stale."
        )
        for wl_imp in wl_imports:
            assert wl_imp in raw_rel_map[wl_path], (
                f"Whitelist import '{wl_imp}' for '{wl_path}' is not present "
                "in the file's imports; the whitelist may be stale."
            )

    # After filtering, no violations should remain (the codebase is clean).
    assert (
        not all_filtered
    ), "Unwhitelisted forbidden imports remain after filtering:\n" + "\n".join(
        f"  {p}: {imp}" for p, imp in all_filtered
    )
