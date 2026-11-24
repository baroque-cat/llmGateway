# src/core/network_guard.py

"""Network outage guard for the gateway and keeper.

The guard detects that the upstream network (the Xray/TUN path in this
deployment) is unavailable and pauses upstream attempts.  Its state is
process-local and is **not** persisted as a durable "down" fact: a container
restart clears it and a startup probe decides whether the service may run.

A small JSON marker in the shared ``data/`` volume coordinates the gateway
workers and the single keeper process.  The marker has a TTL so a dead writer
cannot keep the system paused forever, but a live process never auto-recovers
on its own: only a restart (or an explicit ``mark_up`` at startup) does that.

The module is stdlib-only and deliberately free of service-layer imports.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import ssl
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from src.core.constants import TransportFailureClass

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
TransitionCallback = Callable[[str, dict[str, Any]], None]


class NetworkGuardSettings(Protocol):
    """Structural settings required by :class:`NetworkGuard`.

    ``NetworkGuardConfig`` (the Pydantic schema) satisfies this protocol, but
    ``core`` deliberately does not import the config layer.  Tests can pass
    either the schema or any object with the same attributes.
    """

    enabled: bool
    mode: Literal["log", "pause"]
    probe_urls: list[str]
    probe_interval_sec: int
    probe_connect_timeout_sec: float
    probe_total_timeout_sec: float
    min_probe_successes: int
    fail_threshold: int
    passive_window_sec: int
    passive_min_providers: int
    passive_min_failures: int
    startup_probe: bool
    auto_recover: bool
    marker_path: str


_MARKER_STATE = "down"


class NetworkGuard:
    """Process-local outage state with a shared TTL marker.

    Args:
        config: Validated ``network_guard`` configuration section.
        source: Short process label (``"gateway"`` or ``"keeper"``) used in
            the marker and logs.
        clock: Injectable clock for deterministic tests.
        on_transition: Optional callback invoked on every state transition
            with ``(new_state, evidence)``.  Used by callers to emit metrics
            without making ``core`` depend on the metrics layer.
    """

    def __init__(
        self,
        config: NetworkGuardSettings,
        *,
        source: str,
        clock: Clock = time.time,
        on_transition: TransitionCallback | None = None,
    ) -> None:
        self._config = config
        self._source = source
        self._clock = clock
        self._on_transition = on_transition

        self._down = False
        self._since = 0.0
        self._reason = ""
        self._evidence: dict[str, Any] = {}
        self._last_heartbeat = 0.0
        self._consecutive_probe_failures = 0
        self._passive: deque[tuple[float, str, TransportFailureClass]] = deque()
        self._marker_path = Path(config.marker_path)

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the guard is configured to run."""
        return self._config.enabled

    @property
    def enforcing(self) -> bool:
        """Whether DOWN should actually block requests/probes.

        In ``log`` mode the guard still records state and metrics, but callers
        must not pause traffic.
        """
        return self._config.enabled and self._config.mode == "pause"

    def is_down(self) -> bool:
        """Return True when the guard is in the DOWN state."""
        return self._down

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot for logs and diagnostics."""
        return {
            "enabled": self._config.enabled,
            "mode": self._config.mode,
            "state": "down" if self._down else "up",
            "since": self._since,
            "reason": self._reason,
            "evidence": dict(self._evidence),
            "consecutive_probe_failures": self._consecutive_probe_failures,
        }

    # ------------------------------------------------------------------
    # Passive detection
    # ------------------------------------------------------------------

    def note_failure(
        self, provider_name: str, transport_class: TransportFailureClass
    ) -> None:
        """Record one transport failure for passive outage detection.

        This method is intentionally cheap and synchronous: it must be safe
        to call from a request hot path.  A background ``evaluate()`` call
        performs the actual transition.

        Args:
            provider_name: Provider instance that failed.
            transport_class: Transport-phase classification.
        """
        if not self._config.enabled:
            return

        now = self._clock()
        self._passive.append((now, provider_name, transport_class))
        cutoff = now - self._config.passive_window_sec
        while self._passive and self._passive[0][0] < cutoff:
            self._passive.popleft()

    def _passive_evidence(self) -> dict[str, Any] | None:
        """Return evidence when the passive window crosses the threshold."""
        if not self._passive:
            return None

        providers = {provider for _, provider, _ in self._passive}
        classes = {transport.value for _, _, transport in self._passive}
        if (
            len(providers) < self._config.passive_min_providers
            or len(self._passive) < self._config.passive_min_failures
        ):
            return None

        return {
            "providers": sorted(providers),
            "classes": sorted(classes),
            "count": len(self._passive),
        }

    async def evaluate_passive(self) -> None:
        """Trip DOWN if the passive window crosses the configured threshold."""
        if not self._config.enabled or self._down:
            return

        evidence = self._passive_evidence()
        if evidence is None:
            return

        await self.mark_down("passive_window", evidence)

    # ------------------------------------------------------------------
    # Active probing
    # ------------------------------------------------------------------

    async def _probe_one(self, url: str) -> bool:
        """Open a TCP+TLS connection to one probe target.

        No HTTP request is sent, so no provider quota or API key is used.

        Args:
            url: Target URL; only scheme, host and port are used.

        Returns:
            True when the connection (and TLS handshake for https) succeeded.
        """
        normalized = url if "://" in url else f"https://{url}"
        parsed = urlsplit(normalized)
        host = parsed.hostname
        if not host:
            logger.warning("network_guard: probe URL has no host: %s", url)
            return False

        scheme = (parsed.scheme or "https").lower()
        port = parsed.port or (443 if scheme == "https" else 80)
        use_tls = scheme == "https"

        try:
            async with asyncio.timeout(self._config.probe_connect_timeout_sec):
                context = ssl.create_default_context() if use_tls else None
                reader, writer = await asyncio.open_connection(
                    host,
                    port,
                    ssl=context,
                    server_hostname=host if use_tls else None,
                )
                _ = reader  # keep the reader alive until the connection closes
                writer.close()
                await writer.wait_closed()
            return True
        except Exception as exc:  # noqa: BLE001 - any probe failure is DOWN evidence
            logger.debug(
                "network_guard: probe failed for %s (%s): %s",
                url,
                type(exc).__name__,
                exc,
            )
            return False

    async def probe_once(self) -> bool:
        """Run all configured probes in parallel.

        Returns:
            True when at least ``min_probe_successes`` targets are reachable.
            With no configured targets the active probe is considered
            inconclusive and returns True (the guard then relies on passive
            detection).
        """
        urls = [u for u in self._config.probe_urls if u.strip()]
        if not urls:
            return True

        required = min(self._config.min_probe_successes, len(urls))
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(self._probe_one(url) for url in urls),
                    return_exceptions=False,
                ),
                timeout=self._config.probe_total_timeout_sec,
            )
        except TimeoutError:
            logger.warning(
                "network_guard: probe batch exceeded %.1fs",
                self._config.probe_total_timeout_sec,
            )
            return False

        successes = sum(1 for ok in results if ok)
        return successes >= required

    async def startup_probe(self) -> bool:
        """Decide the initial state at process startup.

        A successful probe clears the marker (this is the manual-reset path).
        A failed probe writes a DOWN marker and keeps the service paused.

        Returns:
            True when the guard starts in the UP state.
        """
        if not self._config.enabled:
            return True
        if not self._config.startup_probe:
            return not self._down
        if not any(url.strip() for url in self._config.probe_urls):
            # No active targets configured: do not clear an existing marker.
            # The poll loop will adopt it if another process wrote one.
            return not self._down

        ok = await self.probe_once()
        if ok:
            await self.mark_up("startup_probe")
        else:
            await self.mark_down(
                "startup_probe", {"probes": len(self._config.probe_urls)}
            )
        return ok

    async def active_loop(self) -> None:
        """Continuously probe the network while the process is alive.

        The loop never auto-recovers a running process: after a successful
        probe it only refreshes the marker.  Recovery requires a restart
        (or ``auto_recover=True`` for explicit opt-in).
        """
        while True:
            try:
                if self._config.enabled:
                    ok = await self.probe_once()
                    if ok:
                        self._consecutive_probe_failures = 0
                        if self._down:
                            if self._config.auto_recover:
                                await self.mark_up("active_probe")
                            elif not self._marker_path.exists():
                                # Another process (e.g. a restarted gateway)
                                # cleared the marker: that is the operator
                                # reset signal, so the keeper may resume.
                                await self.mark_up("marker_cleared")
                            else:
                                await self.heartbeat()
                    else:
                        self._consecutive_probe_failures += 1
                        if (
                            not self._down
                            and self._consecutive_probe_failures
                            >= self._config.fail_threshold
                        ):
                            await self.mark_down(
                                "active_probe",
                                {
                                    "consecutive_failures": (
                                        self._consecutive_probe_failures
                                    )
                                },
                            )
                        elif self._down:
                            await self.heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - loop must survive unexpected errors
                logger.exception("network_guard: active probe loop error")

            await asyncio.sleep(self._config.probe_interval_sec)

    # ------------------------------------------------------------------
    # Shared marker
    # ------------------------------------------------------------------

    def _marker_payload(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Build the marker payload."""
        ttl = max(self._config.probe_interval_sec * 2, 60)
        return {
            "state": _MARKER_STATE,
            "source": self._source,
            "pid": os.getpid(),
            "since": self._since,
            "reason": self._reason,
            "expires_at": self._clock() + ttl,
            "evidence": evidence,
        }

    async def _write_marker(self, evidence: dict[str, Any]) -> None:
        """Atomically write the DOWN marker."""
        payload = self._marker_payload(evidence)

        def _write() -> None:
            self._marker_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._marker_path.with_name(
                f"{self._marker_path.name}.{os.getpid()}.{id(self)}.tmp"
            )
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._marker_path)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            logger.error("network_guard: failed to write marker: %s", exc)

    async def _remove_marker(self) -> None:
        """Remove the DOWN marker, ignoring a missing file."""

        def _remove() -> None:
            with contextlib.suppress(FileNotFoundError):
                self._marker_path.unlink()

        try:
            await asyncio.to_thread(_remove)
        except OSError as exc:
            logger.error("network_guard: failed to remove marker: %s", exc)

    def _read_marker(self) -> dict[str, Any] | None:
        """Read and validate the marker; return None when absent/invalid/expired."""
        try:
            raw = self._marker_path.read_text(encoding="utf-8")
            parsed: Any = json.loads(raw)
        except (OSError, ValueError):
            return None
        if not isinstance(parsed, dict):
            return None
        data = cast(dict[str, Any], parsed)
        if data.get("state") != _MARKER_STATE:
            return None
        expires_at = data.get("expires_at")
        if not isinstance(expires_at, (int, float)) or expires_at < self._clock():
            return None
        return data

    async def poll_marker(self) -> None:
        """Adopt a fresh DOWN marker written by another process.

        A live process never clears its local DOWN state when the marker
        disappears; that requires a restart.
        """
        if not self._config.enabled or self._down:
            return

        data = await asyncio.to_thread(self._read_marker)
        if data is None:
            return

        self._down = True
        self._since = float(data.get("since", self._clock()))
        self._reason = str(data.get("reason", "marker"))
        evidence = data.get("evidence")
        self._evidence = evidence if isinstance(evidence, dict) else {}
        logger.critical(
            "network_guard: DOWN adopted from marker (source=%s, reason=%s, "
            "evidence=%s)",
            data.get("source", "unknown"),
            self._reason,
            self._evidence,
        )
        if self._on_transition is not None:
            self._on_transition("down", {"reason": self._reason, **self._evidence})

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    async def mark_down(self, reason: str, evidence: dict[str, Any]) -> None:
        """Enter the DOWN state and publish the marker.

        Args:
            reason: Short reason label (``passive_window``, ``active_probe``,
                ``startup_probe``, ...).
            evidence: Diagnostic evidence included in logs and the marker.
        """
        if not self._config.enabled:
            return
        if self._down:
            self._reason = reason
            self._evidence = evidence
            await self.heartbeat()
            return

        self._down = True
        self._since = self._clock()
        self._reason = reason
        self._evidence = evidence
        self._last_heartbeat = self._clock()
        logger.critical(
            "network_guard: DOWN (%s) — upstream attempts are paused. "
            "Fix connectivity and restart the container. Evidence: %s",
            reason,
            evidence,
        )
        await self._write_marker(evidence)
        if self._on_transition is not None:
            self._on_transition("down", {"reason": reason, **evidence})

    async def mark_up(self, reason: str) -> None:
        """Enter the UP state and remove the marker.

        Args:
            reason: Short reason label (usually ``startup_probe``).
        """
        if not self._down:
            await self._remove_marker()
            return

        self._down = False
        self._reason = reason
        self._evidence = {}
        self._last_heartbeat = 0.0
        logger.info("network_guard: UP (%s) — upstream attempts are allowed.", reason)
        await self._remove_marker()
        if self._on_transition is not None:
            self._on_transition("up", {})

    async def heartbeat(self) -> None:
        """Refresh the marker TTL while DOWN."""
        if not self._down:
            return
        now = self._clock()
        if now - self._last_heartbeat < self._config.probe_interval_sec:
            return
        self._last_heartbeat = now
        await self._write_marker(self._evidence)

    async def poll_loop(self) -> None:
        """Background loop: adopt remote markers and refresh the local one."""
        while True:
            try:
                await self.poll_marker()
                await self.evaluate_passive()
                if self._down:
                    await self.heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - loop must survive unexpected errors
                logger.exception("network_guard: marker poll loop error")
            await asyncio.sleep(1.0)


# ----------------------------------------------------------------------
# Process-wide singleton
# ----------------------------------------------------------------------

_guard: NetworkGuard | None = None


def set_network_guard(guard: NetworkGuard | None) -> None:
    """Install the process-wide guard (used by ``run_keeper`` and gateway)."""
    global _guard
    _guard = guard


def get_network_guard() -> NetworkGuard | None:
    """Return the process-wide guard, if one has been installed."""
    return _guard
