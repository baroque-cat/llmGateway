"""
E2E tests for multiprocess Gateway behavior.

Tests that require subprocess execution of uvicorn with ``--workers N``:
- E2E-GM01: Both workers respond to HTTP requests on same port
- E2E-GM02: /metrics aggregates metrics from both workers
- E2E-GM03: Worker shutdown → mmap file marked as dead,
             MultiProcessCollector excludes it

These tests verify the prometheus_client multiprocess metrics
infrastructure used by the gateway when ``workers > 1``.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.multiprocess import MultiProcessCollector


# ---------------------------------------------------------------------------
# Helper: build the worker subprocess script
# ---------------------------------------------------------------------------

_WORKER_SCRIPT_TEMPLATE = textwrap.dedent(
    """\
    import os
    import sys
    import time
    import atexit

    # PROMETHEUS_MULTIPROC_DIR must be set BEFORE importing prometheus_client
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = "MULTIPROC_DIR_PLACEHOLDER"

    from prometheus_client import Gauge, Counter, CollectorRegistry
    from prometheus_client.multiprocess import MultiProcessCollector
    from prometheus_client import multiprocess

    worker_pid = os.getpid()

    def cleanup():
        \"\"\"Mark this process's mmap files as dead on exit.\"\"\"  
        multiprocess.mark_process_dead(worker_pid)

    atexit.register(cleanup)

    # Create a fresh registry with MultiProcessCollector
    registry = CollectorRegistry()
    MultiProcessCollector(registry)

    # Create metrics in different multiprocess modes
    gauge_all = Gauge(
        "e2e_test_gauge_all", "Test gauge all mode",
        multiprocess_mode="all", registry=registry,
    )
    gauge_all.set(100.0)

    gauge_live = Gauge(
        "e2e_test_gauge_live", "Test gauge live mode",
        multiprocess_mode="liveall", registry=registry,
    )
    gauge_live.set(200.0)

    counter = Counter("e2e_test_counter", "Test counter", registry=registry)
    counter.inc(5)

    # Print pid for the main test to use
    print(f"PID={worker_pid}", flush=True)

    # Allow mmap writes to flush
    time.sleep(0.3)

    # List files before exit for debugging
    files_before = os.listdir(os.environ["PROMETHEUS_MULTIPROC_DIR"])
    print(f"FILES_BEFORE_EXIT={files_before}", flush=True)
    """
)


def _build_worker_script(multiproc_dir: str) -> str:
    """Return the worker subprocess script with the multiproc dir substituted."""
    return _WORKER_SCRIPT_TEMPLATE.replace(
        '"MULTIPROC_DIR_PLACEHOLDER"', f'"{multiproc_dir}"'
    )


# ---------------------------------------------------------------------------
# Minimal config YAML for full subprocess tests (E2E-GM01 / E2E-GM02)
# ---------------------------------------------------------------------------

_MINIMAL_CONFIG_YAML = textwrap.dedent(
    """\
    metrics:
      enabled: true
      access_token: "test_metrics_token"

    gateway:
      host: "127.0.0.1"
      port: 55301
      workers: 2

    database:
      host: "${DB_HOST}"
      port: ${DB_PORT}
      user: "${DB_USER}"
      password: "${DB_PASSWORD}"
      dbname: "${DB_NAME}"

    providers:
      test-provider:
        provider_type: "gemini"
        enabled: true
        api_base_url: "https://generativelanguage.googleapis.com"
        default_model: "gemini-2.5-flash"
        models:
          gemini-2.5-flash:
            endpoint_suffix: ":generateContent"
            test_payload:
              contents:
                - parts:
                    - text: "Hello"
        access_control:
          gateway_access_token: "test_gateway_token"
    """
)


# ===========================================================================
# Test class
# ===========================================================================


@pytest.mark.e2e
class TestMultiprocessGateway:
    """E2E tests for multiprocess gateway behavior."""

    # -----------------------------------------------------------------------
    # E2E-GM01: Both workers respond to HTTP requests on same port
    # -----------------------------------------------------------------------

    @pytest.mark.skip(
        reason="E2E test: requires container environment with running database "
        "for gateway startup (lifespan requires PostgreSQL connection)"
    )
    def test_e2e_gm01_both_workers_respond(self, tmp_path: Path) -> None:
        """E2E-GM01: ``uvicorn main:app --workers 2`` → both workers respond.

        Full test procedure (requires container infrastructure):

        1. Create a minimal valid ``config/providers.yaml`` in ``tmp_path``
           with database DSN pointing to a running PostgreSQL instance,
           at least one provider configuration, and ``gateway.workers = 2``.
        2. Set required environment variables:
           ``DB_HOST``, ``DB_PORT``, ``DB_USER``, ``DB_PASSWORD``, ``DB_NAME``,
           ``GATEWAY_WORKERS=2``, ``PROMETHEUS_MULTIPROC_DIR=<tmp_path>/prometheus_multiproc``,
           ``METRICS_ACCESS_TOKEN=test_metrics_token``.
        3. Start uvicorn in a subprocess::

               subprocess.Popen([
                   "uvicorn", "main:app",
                   "--workers", "2",
                   "--host", "127.0.0.1",
                   "--port", "55301",
               ])

        4. Wait for server readiness by polling ``/metrics`` with a Bearer token.
        5. Send multiple HTTP requests to ``http://127.0.0.1:55301/`` with valid auth.
        6. Verify all requests receive HTTP responses (status 200 or expected error).
        7. Verify requests are distributed across both workers (check ``/metrics``
           for ``pid`` labels indicating both workers served requests).
        8. Terminate uvicorn subprocess gracefully (SIGTERM → SIGKILL).
        9. Clean up temporary config and env vars.

        **Cannot be run in isolation**: the gateway's ``lifespan`` startup
        requires a live PostgreSQL connection (``init_db_pool`` +
        ``wait_for_schema_ready``). Without a database, the app crashes
        before serving any requests.
        """
        # Write the minimal config YAML (for documentation / future use)
        config_path: Path = tmp_path / "providers.yaml"
        config_path.write_text(_MINIMAL_CONFIG_YAML)
        assert config_path.exists()

    # -----------------------------------------------------------------------
    # E2E-GM02: /metrics aggregates metrics from both workers
    # -----------------------------------------------------------------------

    @pytest.mark.skip(
        reason="E2E test: requires container environment with running database "
        "for gateway startup (lifespan requires PostgreSQL connection)"
    )
    def test_e2e_gm02_metrics_aggregation(self, tmp_path: Path) -> None:
        """E2E-GM02: ``/metrics`` aggregates metrics from both workers.

        Full test procedure (requires container infrastructure):

        1. Same setup as E2E-GM01 with ``--workers 2``.
        2. Send several requests through the gateway to generate metrics data.
        3. Access ``/metrics`` endpoint with valid Bearer token::

               GET /metrics  Authorization: Bearer test_metrics_token

        4. Verify response status 200 and content-type is Prometheus text format.
        5. Verify metrics output contains request-level data:
           - ``llm_gateway_*`` gauge/counter metrics present
           - Values aggregated from both worker processes
           - ``pid`` labels may appear for ``all`` mode gauges
        6. Verify both workers contributed to the metrics:
           - Send requests that trigger different metric updates
           - Check that aggregated values reflect contributions from both workers
        7. Terminate uvicorn subprocess.

        **Cannot be run in isolation**: same database dependency as E2E-GM01.
        """
        # Write the minimal config YAML (for documentation / future use)
        config_path: Path = tmp_path / "providers.yaml"
        config_path.write_text(_MINIMAL_CONFIG_YAML)
        assert config_path.exists()

    # -----------------------------------------------------------------------
    # E2E-GM03: Worker shutdown → mmap file marked as dead,
    #            MultiProcessCollector excludes it
    # -----------------------------------------------------------------------

    def test_e2e_gm03_worker_shutdown_dead_marking(self, tmp_path: Path) -> None:
        """E2E-GM03: Worker shutdown → mmap file marked as dead,
        MultiProcessCollector excludes it.

        Tests the prometheus_client multiprocess cleanup behavior:

        1. A subprocess creates prometheus metrics in a shared mmap directory.
        2. The subprocess exits, calling ``mark_process_dead(pid)`` via atexit.
        3. ``mark_process_dead`` removes gauge files for ``live`` multiprocess
           modes (``liveall``, ``livemax``, ``livemin``, ``livesum``,
           ``livemostrecent``).
        4. ``MultiProcessCollector`` excludes dead worker data for live gauge
           modes (because the files were removed).
        5. Counter and ``all`` mode gauge files **persist** — they are NOT
           removed by ``mark_process_dead``. This is expected behavior:
           counters accumulate across all workers, and ``all`` mode gauges
           merge values from all files (including dead workers).

        **Also reveals BUG**: ``gateway_service._cleanup_multiproc_files``
        passes ``PROMETHEUS_MULTIPROC_DIR`` (a directory path string) as
        the first argument to ``mark_process_dead``, but the function expects
        a ``pid`` (int). This makes the cleanup effectively a no-op.
        See ``test_e2e_gm03_bug_cleanup_wrong_arg`` for details.
        """
        multiproc_dir: str = str(tmp_path / "prometheus_multiproc")
        os.makedirs(multiproc_dir, exist_ok=True)

        # --- Phase 1: Run worker subprocess that creates metrics and exits ---
        helper_script: Path = tmp_path / "worker_process.py"
        helper_script.write_text(_build_worker_script(multiproc_dir))

        env: dict[str, Any] = os.environ.copy()
        env["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir

        result: subprocess.CompletedProcess[str] = subprocess.run(
            [sys.executable, str(helper_script)],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )

        assert result.returncode == 0, (
            f"Worker subprocess failed (rc={result.returncode}).\n"
            f"stderr: {result.stderr[:500]}"
        )

        # Extract the worker pid from stdout
        pid_lines: list[str] = [
            line for line in result.stdout.splitlines() if line.startswith("PID=")
        ]
        assert len(pid_lines) == 1, (
            f"Expected exactly one 'PID=' line in stdout, got: {result.stdout}"
        )
        worker_pid: int = int(pid_lines[0].split("=")[1])
        # worker_pid is extracted for documentation/debugging;
        # the atexit handler inside the subprocess already used it
        # to call mark_process_dead. We verify the EFFECT of that
        # call by checking which files remain in the directory.
        _ = worker_pid

        # --- Phase 2: Verify mmap files after worker exit ---
        files_after_exit: list[str] = os.listdir(multiproc_dir)
        assert len(files_after_exit) > 0, (
            "No mmap files were created by the worker subprocess"
        )

        # ``mark_process_dead(pid)`` removes gauge files for "live" modes.
        # After the worker exits and its atexit handler calls
        # ``mark_process_dead(worker_pid)``, gauge files with live modes
        # (liveall, livemax, etc.) should have been removed.
        live_gauge_files: list[str] = [
            f
            for f in files_after_exit
            if f.startswith("gauge_live") and f.endswith(".db")
        ]
        assert len(live_gauge_files) == 0, (
            f"Live-mode gauge files should have been removed by "
            f"mark_process_dead(pid), but found: {live_gauge_files}"
        )

        # ``mark_process_dead`` does NOT remove "all" mode gauge files.
        # These persist so that MultiProcessCollector can merge values
        # from all workers (including dead ones).
        all_gauge_files: list[str] = [
            f
            for f in files_after_exit
            if f.startswith("gauge_all") and f.endswith(".db")
        ]
        assert len(all_gauge_files) > 0, (
            f"'all' mode gauge files should persist after mark_process_dead, "
            f"but found none. Files: {files_after_exit}"
        )

        # Counter files are never removed by ``mark_process_dead``.
        # Counter values accumulate across all workers.
        counter_files: list[str] = [
            f
            for f in files_after_exit
            if f.startswith("counter") and f.endswith(".db")
        ]
        assert len(counter_files) > 0, (
            f"Counter files should persist after mark_process_dead, "
            f"but found none. Files: {files_after_exit}"
        )

        # --- Phase 3: Verify MultiProcessCollector aggregation ---
        original_multiproc: str | None = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir

        try:
            registry: CollectorRegistry = CollectorRegistry()
            MultiProcessCollector(registry)
            metrics_output: str = generate_latest(registry).decode()

            # The "live" gauge should NOT appear in metrics output
            # (its mmap files were removed by mark_process_dead).
            assert "e2e_test_gauge_live" not in metrics_output, (
                "Live-mode gauge from dead worker should be excluded by "
                "MultiProcessCollector (mmap files removed), but found "
                "in metrics output"
            )

            # The "all" mode gauge WILL appear in metrics output
            # (its mmap files persist — dead worker data is included).
            # This is expected: "all" mode merges values from all files.
            assert "e2e_test_gauge_all" in metrics_output, (
                "'all' mode gauge from dead worker should still appear in "
                "metrics output (mmap files persist for 'all' mode)"
            )

            # Counter values from dead worker will also appear
            # (counter files are never removed by mark_process_dead).
            assert "e2e_test_counter" in metrics_output, (
                "Counter from dead worker should still appear in metrics "
                "output (counter files persist)"
            )

        finally:
            # Restore original env var
            if original_multiproc is not None:
                os.environ["PROMETHEUS_MULTIPROC_DIR"] = original_multiproc
            else:
                os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

    # -----------------------------------------------------------------------
    # E2E-GM03 supplementary: BUG in _cleanup_multiproc_files
    # -----------------------------------------------------------------------

    def test_e2e_gm03_bug_cleanup_wrong_arg(self) -> None:
        """E2E-GM03 (supplementary): Verify BUG in ``_cleanup_multiproc_files``.

        **BUG REPORT**

        - **File**: ``src/services/gateway/gateway_service.py``
        - **Lines**: 886–897 (inside the ``lifespan`` function)
        - **Expected**: ``multiprocess.mark_process_dead(os.getpid())``
          — passes the integer pid of the current worker process.
        - **Actual**: ``multiprocess.mark_process_dead(os.environ.get(
          "PROMETHEUS_MULTIPROC_DIR", "/tmp/prometheus_multiproc"))``
          — passes a **directory path string** as the ``pid`` argument.
        - **Impact**: ``mark_process_dead`` builds a glob pattern
          ``gauge_{mode}_{path_string}.db`` which never matches any real
          mmap file. The cleanup is effectively a **no-op** — dead worker
          gauge files for ``live`` modes are never removed.
        - **Severity**: HIGH — in production with ``workers > 1``, stale
          ``live`` gauge data from exited workers accumulates indefinitely
          because ``mark_process_dead`` never removes the correct files.

        This test verifies the bug is FIXED by reading the source code
        and confirming the correct argument pattern.
        """
        source_path: Path = Path(
            "src/services/gateway/gateway_service.py"
        )
        source_text: str = source_path.read_text()

        # Find the _cleanup_multiproc_files function definition
        assert "_cleanup_multiproc_files" in source_text, (
            "Expected _cleanup_multiproc_files function in gateway_service.py"
        )

        # Extract the cleanup function body
        cleanup_section: str = source_text[
            source_text.index("def _cleanup_multiproc_files") :
        ]
        cleanup_end: int = cleanup_section.index("if gw_workers > 1:")
        cleanup_body: str = cleanup_section[:cleanup_end]

        # BUG FIX VERIFIED: mark_process_dead now receives os.getpid()
        # (an integer pid) instead of PROMETHEUS_MULTIPROC_DIR (a string path).
        assert "os.getpid()" in cleanup_body, (
            "BUG FIX VERIFIED: _cleanup_multiproc_files now correctly "
            "uses os.getpid() as the pid argument to mark_process_dead."
        )

    # -----------------------------------------------------------------------
    # E2E-GM03 supplementary: Correct mark_process_dead behavior
    # -----------------------------------------------------------------------

    def test_e2e_gm03_correct_mark_process_dead_removes_live_gauges(
        self, tmp_path: Path
    ) -> None:
        """E2E-GM03 (supplementary): Verify correct ``mark_process_dead(pid)``
        removes live-mode gauge files.

        This test demonstrates what the CORRECT cleanup behavior should
        look like — i.e., what ``_cleanup_multiproc_files`` SHOULD do
        if it passed ``os.getpid()`` instead of a directory path.

        Steps:
        1. Create a subprocess that writes prometheus metrics with both
           ``all`` and ``liveall`` mode gauges.
        2. The subprocess does NOT register an atexit handler (so files
           persist after exit).
        3. After the subprocess exits, manually call
           ``mark_process_dead(worker_pid)`` from the main test process.
        4. Verify that ``liveall`` gauge files are removed.
        5. Verify that ``all`` gauge files and counter files persist.
        """
        multiproc_dir: str = str(tmp_path / "prometheus_multiproc")
        os.makedirs(multiproc_dir, exist_ok=True)

        # Build a worker script WITHOUT atexit cleanup
        worker_script_no_cleanup: str = textwrap.dedent(
            """\
            import os
            import sys
            import time

            os.environ["PROMETHEUS_MULTIPROC_DIR"] = "MULTIPROC_DIR_PLACEHOLDER"

            from prometheus_client import Gauge, Counter, CollectorRegistry
            from prometheus_client.multiprocess import MultiProcessCollector

            registry = CollectorRegistry()
            MultiProcessCollector(registry)

            gauge_all = Gauge(
                "e2e_correct_gauge_all", "Correct test gauge all",
                multiprocess_mode="all", registry=registry,
            )
            gauge_all.set(50.0)

            gauge_live = Gauge(
                "e2e_correct_gauge_live", "Correct test gauge live",
                multiprocess_mode="liveall", registry=registry,
            )
            gauge_live.set(75.0)

            counter = Counter(
                "e2e_correct_counter", "Correct test counter",
                registry=registry,
            )
            counter.inc(3)

            print(f"PID={os.getpid()}", flush=True)
            time.sleep(0.3)
            """
        ).replace('"MULTIPROC_DIR_PLACEHOLDER"', f'"{multiproc_dir}"')

        script_path: Path = tmp_path / "worker_no_cleanup.py"
        script_path.write_text(worker_script_no_cleanup)

        env: dict[str, Any] = os.environ.copy()
        env["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir

        result: subprocess.CompletedProcess[str] = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )

        assert result.returncode == 0, (
            f"Worker subprocess failed (rc={result.returncode}).\n"
            f"stderr: {result.stderr[:500]}"
        )

        pid_lines: list[str] = [
            line for line in result.stdout.splitlines() if line.startswith("PID=")
        ]
        assert len(pid_lines) == 1, f"Expected one PID line, got: {result.stdout}"
        worker_pid: int = int(pid_lines[0].split("=")[1])

        # Before calling mark_process_dead, all files should exist
        files_before_cleanup: list[str] = os.listdir(multiproc_dir)
        live_files_before: list[str] = [
            f
            for f in files_before_cleanup
            if f.startswith("gauge_live") and f.endswith(".db")
        ]
        assert len(live_files_before) > 0, (
            f"Expected live gauge files before cleanup, "
            f"but found none. Files: {files_before_cleanup}"
        )

        # --- Call mark_process_dead with the CORRECT pid ---
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(worker_pid, path=multiproc_dir)  # pyright: ignore[reportUnknownMemberType]

        # After mark_process_dead, live gauge files should be removed
        files_after_cleanup: list[str] = os.listdir(multiproc_dir)
        live_files_after: list[str] = [
            f
            for f in files_after_cleanup
            if f.startswith("gauge_live") and f.endswith(".db")
        ]
        assert len(live_files_after) == 0, (
            f"mark_process_dead(pid) should remove live gauge files, "
            f"but found: {live_files_after}"
        )

        # "all" mode gauge files should persist
        all_files_after: list[str] = [
            f
            for f in files_after_cleanup
            if f.startswith("gauge_all") and f.endswith(".db")
        ]
        assert len(all_files_after) > 0, (
            f"'all' mode gauge files should persist after mark_process_dead, "
            f"but found none. Files: {files_after_cleanup}"
        )

        # Counter files should persist
        counter_files_after: list[str] = [
            f
            for f in files_after_cleanup
            if f.startswith("counter") and f.endswith(".db")
        ]
        assert len(counter_files_after) > 0, (
            f"Counter files should persist after mark_process_dead, "
            f"but found none. Files: {files_after_cleanup}"
        )

        # --- Verify MultiProcessCollector aggregation after cleanup ---
        original_multiproc: str | None = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir

        try:
            registry: CollectorRegistry = CollectorRegistry()
            MultiProcessCollector(registry)
            metrics_output: str = generate_latest(registry).decode()

            # Live gauge should NOT appear (files removed)
            assert "e2e_correct_gauge_live" not in metrics_output, (
                "Live gauge from dead worker should be excluded after "
                "mark_process_dead(pid) removed its mmap files"
            )

            # "all" mode gauge should appear (files persist)
            assert "e2e_correct_gauge_all" in metrics_output, (
                "'all' mode gauge from dead worker should still appear "
                "(mmap files persist for 'all' mode)"
            )

            # Counter should appear (files persist)
            assert "e2e_correct_counter" in metrics_output, (
                "Counter from dead worker should still appear "
                "(counter files persist)"
            )

        finally:
            if original_multiproc is not None:
                os.environ["PROMETHEUS_MULTIPROC_DIR"] = original_multiproc
            else:
                os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)