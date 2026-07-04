"""Gatekeeper tests for ``.pre-commit-config.yaml`` hook configuration.

Parses the pre-commit config and asserts that each expected hook ID is present
with the correct configuration (args, files scope, entry command, etc.).

Coverage map entries #25-#32:
    #25: ``trailing-whitespace`` hook configured.
    #26: ``end-of-file-fixer`` hook configured.
    #27: ``check-yaml``, ``check-toml``, ``check-json`` hooks configured.
    #28: ``check-merge-conflict`` hook configured.
    #29: ``detect-private-key`` hook configured.
    #30: ``mixed-line-ending`` hook configured with ``--fix=lf``.
    #31: ``pyright`` local hook targets ``src/`` and ``main.py`` only.
    #32: ``shellcheck`` hook lints the ``scripts/`` directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Repo URLs used in .pre-commit-config.yaml.
_PRE_COMMIT_HOOKS_REPO: str = "https://github.com/pre-commit/pre-commit-hooks"
_SHELLCHECK_REPO: str = "https://github.com/koalaman/shellcheck-precommit"
_LOCAL_REPO: str = "local"


def _load_precommit_config() -> dict[str, Any]:
    """Parse ``.pre-commit-config.yaml`` and return it as a dict.

    Returns:
        The parsed pre-commit configuration as a dictionary.

    Raises:
        AssertionError: If the parsed YAML is not a dict.
    """
    with open(_REPO_ROOT / ".pre-commit-config.yaml") as f:
        data: Any = yaml.safe_load(f)
    assert isinstance(data, dict), ".pre-commit-config.yaml did not parse to a dict"
    return cast("dict[str, Any]", data)


def _get_hooks_from_repo(repo_url: str) -> list[dict[str, Any]]:
    """Get all hooks from a specific repo URL.

    Args:
        repo_url: The repo URL to search for (e.g.,
            ``https://github.com/pre-commit/pre-commit-hooks``).

    Returns:
        List of hook configuration dicts. Empty list if the repo is not found.
    """
    config: dict[str, Any] = _load_precommit_config()
    repos: list[dict[str, Any]] = cast("list[dict[str, Any]]", config.get("repos", []))
    for repo in repos:
        if repo.get("repo") == repo_url:
            return cast("list[dict[str, Any]]", repo.get("hooks", []))
    return []


def _find_hook(hooks: list[dict[str, Any]], hook_id: str) -> dict[str, Any] | None:
    """Find a hook by ID in a list of hooks.

    Args:
        hooks: List of hook configuration dicts.
        hook_id: Hook ID to search for.

    Returns:
        Hook dict or ``None`` if not found.
    """
    for hook in hooks:
        if hook.get("id") == hook_id:
            return hook
    return None


def test_trailing_whitespace_hook_configured() -> None:
    """#25: ``trailing-whitespace`` hook exists in pre-commit-hooks repo."""
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_PRE_COMMIT_HOOKS_REPO)
    hook: dict[str, Any] | None = _find_hook(hooks, "trailing-whitespace")
    assert (
        hook is not None
    ), "trailing-whitespace hook not found in pre-commit-hooks repo"


def test_end_of_file_fixer_hook_configured() -> None:
    """#26: ``end-of-file-fixer`` hook exists in pre-commit-hooks repo."""
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_PRE_COMMIT_HOOKS_REPO)
    hook: dict[str, Any] | None = _find_hook(hooks, "end-of-file-fixer")
    assert hook is not None, "end-of-file-fixer hook not found in pre-commit-hooks repo"


def test_check_yaml_toml_json_hooks_configured() -> None:
    """#27: ``check-yaml``, ``check-toml``, ``check-json`` hooks all exist."""
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_PRE_COMMIT_HOOKS_REPO)
    for hook_id in ("check-yaml", "check-toml", "check-json"):
        hook: dict[str, Any] | None = _find_hook(hooks, hook_id)
        assert hook is not None, f"{hook_id} hook not found in pre-commit-hooks repo"


def test_check_merge_conflict_hook_configured() -> None:
    """#28: ``check-merge-conflict`` hook exists in pre-commit-hooks repo."""
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_PRE_COMMIT_HOOKS_REPO)
    hook: dict[str, Any] | None = _find_hook(hooks, "check-merge-conflict")
    assert (
        hook is not None
    ), "check-merge-conflict hook not found in pre-commit-hooks repo"


def test_detect_private_key_hook_configured() -> None:
    """#29: ``detect-private-key`` hook exists in pre-commit-hooks repo."""
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_PRE_COMMIT_HOOKS_REPO)
    hook: dict[str, Any] | None = _find_hook(hooks, "detect-private-key")
    assert (
        hook is not None
    ), "detect-private-key hook not found in pre-commit-hooks repo"


def test_mixed_line_ending_hook_configured() -> None:
    """#30: ``mixed-line-ending`` hook exists with ``--fix=lf`` arg."""
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_PRE_COMMIT_HOOKS_REPO)
    hook: dict[str, Any] | None = _find_hook(hooks, "mixed-line-ending")
    assert hook is not None, "mixed-line-ending hook not found in pre-commit-hooks repo"
    args: list[str] = cast("list[str]", hook.get("args", []))
    assert (
        "--fix=lf" in args
    ), "mixed-line-ending hook must have args containing --fix=lf"


def test_pyright_hook_targets_src_and_main_only() -> None:
    """#31: ``pyright`` local hook targets ``src/`` and ``main.py`` only.

    Verifies the local ``pyright`` hook:
        - Entry contains ``poetry run pyright src/ main.py``.
        - ``pass_filenames`` is ``False``.
        - ``files`` pattern scopes to ``src/`` and ``main.py``.
    """
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_LOCAL_REPO)
    hook: dict[str, Any] | None = _find_hook(hooks, "pyright")
    assert hook is not None, "pyright hook not found in local repo"

    entry: str = cast("str", hook.get("entry", ""))
    assert (
        "poetry run pyright src/ main.py" in entry
    ), "pyright hook entry must contain 'poetry run pyright src/ main.py'"

    pass_filenames: bool = cast("bool", hook.get("pass_filenames", True))
    assert pass_filenames is False, "pyright hook must set pass_filenames: false"

    files: str = cast("str", hook.get("files", ""))
    assert (
        files == r"^src/|^main\.py$"
    ), f"pyright hook files must scope to src/ and main.py only, got: {files!r}"


def test_shellcheck_hook_lints_scripts_directory() -> None:
    """#32: ``shellcheck`` hook lints only the ``scripts/`` directory."""
    hooks: list[dict[str, Any]] = _get_hooks_from_repo(_SHELLCHECK_REPO)
    hook: dict[str, Any] | None = _find_hook(hooks, "shellcheck")
    assert hook is not None, "shellcheck hook not found in shellcheck-precommit repo"

    files: str = cast("str", hook.get("files", ""))
    assert (
        files == "^scripts/"
    ), f"shellcheck hook files must be scoped to '^scripts/', got: {files!r}"
