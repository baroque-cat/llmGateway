"""Security gatekeeper test scanning for hardcoded secrets and keys.

Verifies that no hardcoded passwords, private keys, or committed ``.env``
files exist in the repository.  Implements scenarios from the
security-gatekeeper-tests spec (coverage map entries #7-#10).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Extensions that indicate private key or certificate files.
_PRIVATE_KEY_EXTENSIONS: set[str] = {".pem", ".key", ".crt", ".p12", ".pfx"}

# Filenames that indicate SSH private keys.
_PRIVATE_KEY_NAMES: set[str] = {"id_rsa", "id_ed25519"}

# Directories to skip during filesystem scanning.
_SKIP_DIRS: set[str] = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
}

# Self-signed test certificates for the stress-test HTTP/2 server.
# Generated for localhost (127.0.0.1); not real production secrets.
_ALLOWED_KEY_FILES: set[str] = {
    "tests/stress/key.pem",
    "tests/stress/cert.pem",
}

# Password-assignment pattern: catches ``password="value"`` (with single or
# double quotes) but not benign references like ``password`` in docstrings.
_PASSWORD_RE: re.Pattern[str] = re.compile(
    r'password\s*=\s*["\'][^"\']+["\']', re.IGNORECASE
)


def _is_in_skip_dir(path: Path) -> bool:
    """Check if a path is inside a skip directory.

    Args:
        path: File path to check.

    Returns:
        True if any path component is in ``_SKIP_DIRS``.
    """
    return any(part in _SKIP_DIRS for part in path.parts)


def _iter_py_files(root: Path) -> list[Path]:
    """Return all ``.py`` files under *root*, skipping excluded directories.

    Args:
        root: Directory to scan recursively.

    Returns:
        Sorted list of ``.py`` file paths.
    """
    result: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if _is_in_skip_dir(path):
            continue
        result.append(path)
    return result


def test_env_in_gitignore() -> None:
    """Verify ``.env`` is listed in ``.gitignore`` (spec: .env in .gitignore).

    Ensures that the real ``.env`` file (containing live credentials) cannot
    be accidentally committed to version control.
    """
    gitignore_path = _REPO_ROOT / ".gitignore"
    assert gitignore_path.is_file(), "Missing .gitignore at repo root"
    content = gitignore_path.read_text(encoding="utf-8")
    assert ".env" in content, ".env must be listed in .gitignore"


def test_no_hardcoded_passwords_in_source_files() -> None:
    """Verify no hardcoded passwords in ``src/`` (spec: no hardcoded passwords).

    Scans all ``.py`` files under ``src/`` for password-assignment patterns
    like ``password="secret"``.  Comment lines are skipped to avoid false
    positives from example documentation.
    """
    src_dir = _REPO_ROOT / "src"
    assert src_dir.is_dir(), "Missing src/ directory"

    violations: list[str] = []
    for py_file in _iter_py_files(src_dir):
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if _PASSWORD_RE.search(line):
                violations.append(f"{py_file}:{line_num}: {line.strip()}")

    assert (
        not violations
    ), "Hardcoded password patterns found in source files:\n" + "\n".join(violations)


def test_no_private_key_files_committed() -> None:
    """Verify no private key files committed (spec: no private key files).

    Scans the repository for files with private-key extensions (``.pem``,
    ``.key``, ``.crt``, ``.p12``, ``.pfx``) and private-key names
    (``id_rsa``, ``id_ed25519``).  Self-signed test certificates for the
    stress-test HTTP/2 server are allowlisted.
    """
    found: list[str] = []

    # Check by extension
    for ext in _PRIVATE_KEY_EXTENSIONS:
        for path in _REPO_ROOT.rglob(f"*{ext}"):
            if not path.is_file():
                continue
            if _is_in_skip_dir(path):
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel in _ALLOWED_KEY_FILES:
                continue
            found.append(f"{rel} (extension {path.suffix})")

    # Check by name
    for name in _PRIVATE_KEY_NAMES:
        for path in _REPO_ROOT.rglob(name):
            if not path.is_file():
                continue
            if _is_in_skip_dir(path):
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            found.append(f"{rel} (name {path.name})")

    assert not found, "Private key files found in repository:\n" + "\n".join(
        sorted(set(found))
    )


def test_no_committed_env_files_except_example() -> None:
    """Verify no committed ``.env`` files except ``.env.example`` (spec).

    Uses ``git ls-files`` to check only committed files.  The local ``.env``
    file is gitignored and therefore not considered committed.
    """
    proc = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )
    assert proc.returncode == 0, f"git ls-files failed: {proc.stderr}"

    committed_files = proc.stdout.splitlines()
    env_files = [f for f in committed_files if ".env" in Path(f).name]

    assert env_files == [
        ".env.example"
    ], f"Expected only .env.example, found: {env_files}"
