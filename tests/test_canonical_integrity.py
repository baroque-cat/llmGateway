"""Structural tests verifying CanonicalConfig integrity (Scenarios S19, S3).

Ensures that CanonicalConfig is complete, frozen, deterministic, and that
config test files use the canonical approach instead of hardcoded dicts.
"""

import dataclasses
import re
from pathlib import Path

import pytest

from tests._canonical import CanonicalConfig

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

_CONFIG_TEST_FILES: list[Path] = [
    _REPO_ROOT / "tests" / "unit" / "config" / "test_loader.py",
    _REPO_ROOT / "tests" / "unit" / "config" / "test_config_init.py",
    _REPO_ROOT / "tests" / "unit" / "config" / "test_gateway_config.py",
    _REPO_ROOT / "tests" / "unit" / "config" / "test_resolve_env_vars.py",
]


def test_canonical_integrity_verifies_completeness() -> None:
    """Verify CanonicalConfig has >=40 fields, 17 env vars, and is frozen (S19).

    Checks:
        - At least 40 dataclass fields
        - ``to_env_dict()`` returns exactly 17 env vars
        - All values in ``to_env_dict()`` are strings
        - Config is frozen (cannot set attributes)
        - ``from_example_files()`` returns equal instances on multiple calls
    """
    cfg = CanonicalConfig.from_example_files()

    # --- Field count ---
    fields = dataclasses.fields(cfg)
    assert (
        len(fields) >= 40
    ), f"CanonicalConfig should have >=40 fields, got {len(fields)}"

    # --- Env dict completeness ---
    env_dict = cfg.to_env_dict()
    assert (
        len(env_dict) == 17
    ), f"to_env_dict() should return 17 env vars, got {len(env_dict)}"

    # --- All values are strings (runtime verification of type guarantee) ---
    non_str_keys = [
        k
        for k, v in env_dict.items()
        if not isinstance(v, str)  # pyright: ignore[reportUnnecessaryIsInstance]
    ]
    assert (
        not non_str_keys
    ), f"Non-string values in to_env_dict() for keys: {non_str_keys}"

    # --- Frozen check (setattr avoids pyright readonly-assignment error) ---
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(cfg, "db_host", "should_fail")  # noqa: B010

    # --- Determinism (cached parse produces equal instances) ---
    cfg2 = CanonicalConfig.from_example_files()
    assert (
        cfg == cfg2
    ), "from_example_files() should return equal configs (cached parse)"


def test_no_duplicated_base_env_dicts() -> None:
    """Verify config test files use CanonicalConfig, not hardcoded dicts (S3).

    Checks:
        - Each file imports from ``tests._canonical``
        - Each file uses ``CanonicalConfig.from_example_files().to_env_dict()``
        - No file contains a hardcoded ``_BASE_ENV = {`` dict literal
    """
    hardcoded_pattern = re.compile(r"_BASE_ENV\b.*=\s*\{")

    for test_file in _CONFIG_TEST_FILES:
        assert test_file.is_file(), f"Config test file not found: {test_file}"
        content = test_file.read_text(encoding="utf-8")

        # --- Import check ---
        assert (
            "from tests._canonical import" in content
        ), f"{test_file.name} should import from tests._canonical"

        # --- Canonical usage check ---
        assert (
            "CanonicalConfig.from_example_files()" in content
        ), f"{test_file.name} should use CanonicalConfig.from_example_files()"

        # --- No hardcoded dict literal ---
        match = hardcoded_pattern.search(content)
        assert match is None, (
            f"{test_file.name} contains hardcoded _BASE_ENV dict literal "
            f"at position {match.start() if match else -1}"
        )
