"""HTTP client for the local ``awareness-markets`` service.

* Base URL: ``SHOWME_AWARENESS_URL`` (default ``http://127.0.0.1:8086``).
* Autostart (default on, ``SHOWME_AWARENESS_AUTOSTART=0`` disables): when the
  service is not reachable and an awareness checkout with a virtualenv exists
  (``SHOWME_AWARENESS_HOME``, default ``~/awareness``), the client launches
  ``python -m awareness.markets.app`` detached and waits briefly for it.
* Honesty contract: the client never fabricates data. Failures raise
  :class:`AwarenessUnavailable` with a human-readable reason; functions turn that
  into a ``provider_unavailable`` status.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

LOG = logging.getLogger("showme.awareness")

DEFAULT_AWARENESS_URL = "http://127.0.0.1:8086"
REQUEST_TIMEOUT = 6.0
AUTOSTART_WAIT_S = 20.0
AUTOSTART_COOLDOWN_S = 120.0
PROVIDER_NAME = "awareness"


def awareness_base_url() -> str:
    return os.environ.get("SHOWME_AWARENESS_URL", DEFAULT_AWARENESS_URL).rstrip("/")


def _autostart_enabled() -> bool:
    raw = os.environ.get("SHOWME_AWARENESS_AUTOSTART", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def awareness_home() -> Path:
    override = os.environ.get("SHOWME_AWARENESS_HOME")
    return Path(override).expanduser() if override else Path.home() / "awareness"


def _awareness_python(home: Path) -> Path | None:
    for candidate in (
        home / ".venv" / "Scripts" / "python.exe",
        home / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return candidate
    return None


class AwarenessUnavailable(RuntimeError):
    """The awareness service could not answer; ``reason`` is safe to show in the UI."""

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass
class AwarenessResponse:
    """A decoded ``{"data", "meta"}`` envelope from awareness."""

    data: Any
    meta: dict[str, Any] = field(default_factory=dict)
    url: str = ""
    elapsed_ms: float = 0.0

    @property
    def providers(self) -> list[dict[str, Any]]:
        return list(self.meta.get("providers") or [])

    @property
    def notes(self) -> list[str]:
        return [str(n) for n in (self.meta.get("notes") or [])]

    @property
    def stale_providers(self) -> list[str]:
        return [p.get("provider", "?") for p in self.providers if p.get("status") in {"down", "degraded"}]

    @property
    def generated_at(self) -> str | None:
        value = self.meta.get("generated_at")
        return str(value) if value else None

    def provenance(self) -> dict[str, Any]:
        """Compact provenance block for FunctionResult.metadata."""
        return {
            "provider": PROVIDER_NAME,
            "service_url": awareness_base_url(),
            "generated_at": self.generated_at,
            "providers": self.providers,
            "notes": self.notes,
        }


class AwarenessClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = REQUEST_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        autostart: bool | None = None,
    ) -> None:
        self.base_url = (base_url or awareness_base_url()).rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._autostart = _autostart_enabled() if autostart is None else autostart
        self._last_autostart = 0.0
        self._autostart_lock = asyncio.Lock()

    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> AwarenessResponse:
        url = f"{self.base_url}{path}"
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "", [], ())}
        for key, value in list(clean.items()):
            if isinstance(value, (list, tuple, set)):
                clean[key] = ",".join(str(v) for v in value)
            elif isinstance(value, bool):
                clean[key] = "true" if value else "false"
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            response = await client.request(method, url, params=clean, json=json)
        elapsed = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("detail", ""))
            except Exception:  # noqa: BLE001 - non-JSON error body
                detail = response.text[:200]
            raise AwarenessUnavailable(
                f"awareness answered HTTP {response.status_code} for {path}: {detail}".strip(),
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AwarenessUnavailable(f"awareness returned non-JSON for {path}") from exc
        if not isinstance(payload, dict) or "data" not in payload:
            raise AwarenessUnavailable(f"awareness returned an unexpected payload for {path}")
        return AwarenessResponse(data=payload["data"], meta=payload.get("meta") or {}, url=str(response.url), elapsed_ms=elapsed)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> AwarenessResponse:
        """GET ``/v1/markets{path}``; autostarts the service once if it is not running."""
        full = f"/v1/markets{path}" if not path.startswith("/v1/") else path
        try:
            return await self._request("GET", full, params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if await self._try_autostart():
                try:
                    return await self._request("GET", full, params=params)
                except httpx.HTTPError as retry_exc:
                    # A timeout can carry an empty message: name the exception type instead.
                    raise AwarenessUnavailable(
                        f"awareness service did not answer after autostart: {str(retry_exc) or type(retry_exc).__name__}"
                    ) from retry_exc
            raise AwarenessUnavailable(
                f"awareness service is not running at {self.base_url} "
                f"(start it with `awareness-markets` in {awareness_home()})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AwarenessUnavailable(f"awareness service timed out after {self.timeout:.0f}s for {full}") from exc
        except httpx.HTTPError as exc:
            raise AwarenessUnavailable(f"awareness request failed: {type(exc).__name__}: {exc}") from exc

    async def post(self, path: str, body: Any) -> AwarenessResponse:
        full = f"/v1/markets{path}"
        try:
            return await self._request("POST", full, json=body)
        except httpx.HTTPError as exc:
            raise AwarenessUnavailable(f"awareness request failed: {type(exc).__name__}: {exc}") from exc

    async def healthz(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=2.0, transport=self._transport) as client:
                response = await client.get(f"{self.base_url}/healthz")
            return response.json() if response.status_code == 200 else None
        except Exception:  # noqa: BLE001 - probe only
            return None

    async def _try_autostart(self) -> bool:
        if not self._autostart or self._transport is not None:
            return False
        async with self._autostart_lock:
            if await self.healthz():
                return True
            if time.monotonic() - self._last_autostart < AUTOSTART_COOLDOWN_S:
                return False
            self._last_autostart = time.monotonic()
            home = awareness_home()
            python = _awareness_python(home)
            if python is None:
                LOG.warning("awareness autostart skipped: no virtualenv under %s", home)
                return False
            port = self.base_url.rsplit(":", 1)[-1].split("/")[0]
            log_dir = home / "data" / "markets"
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = open(log_dir / "service.log", "ab")  # noqa: SIM115 - handed to the child
                kwargs: dict[str, Any] = {
                    "cwd": str(home),
                    "stdout": log_file,
                    "stderr": subprocess.STDOUT,
                    "stdin": subprocess.DEVNULL,
                }
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                else:
                    kwargs["start_new_session"] = True
                subprocess.Popen(  # noqa: S603 - fixed argv, local interpreter
                    [str(python), "-m", "awareness.markets.app", "--port", port],
                    **kwargs,
                )
                LOG.info("awareness-markets autostarted from %s on port %s", home, port)
            except OSError as exc:
                LOG.warning("awareness autostart failed: %s", exc)
                return False
            deadline = time.monotonic() + AUTOSTART_WAIT_S
            while time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                if await self.healthz():
                    return True
            return False


_CLIENT: AwarenessClient | None = None


def get_awareness_client() -> AwarenessClient:
    """Process-wide client (base URL read once per process)."""
    global _CLIENT  # noqa: PLW0603 - module-level singleton by design
    if _CLIENT is None or _CLIENT.base_url != awareness_base_url():
        _CLIENT = AwarenessClient()
    return _CLIENT
