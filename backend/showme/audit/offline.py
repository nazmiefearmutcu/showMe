"""Offline honesty audit (T10): cut the network, call every function.

With no provider reachable a function may only return an honest state
(``provider_unavailable`` / ``empty`` / ``needs_input``), results computed
from the caller's own inputs (labelled model/reference) or the user's local
records. It must never claim live data, show placeholder values or crash.
:func:`run` calls ``/api/fn/<CODE>`` in-process - the same route, router
defaults and sanitizer the UI uses - inside :func:`network_cut` and grades
every response with the response-level truth checks plus three rules:

* ``T10:offline_live_claim`` (red) - an ok response labelled live while every
  outbound connection is refused (the data cannot be live);
* ``T10:offline_crash`` (red) - HTTP 5xx or a non-JSON body;
* ``T10:offline_slow`` (amber) - the call outlived the budget: something
  retries or sleeps instead of failing fast.

Run it as ``python -m showme.audit.offline`` (it always uses a throw-away
SHOWME_HOME with bots off unless ``--home`` is given). Counts are ratcheted in
``tests/_offline_baseline.json`` by ``tests/test_offline_honesty.py``.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import json
import os
import socket
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from showme.audit import truth

BASELINE_PATH = truth.REPO_ROOT / "tests" / "_offline_baseline.json"
DEAD_PROXY = "http://127.0.0.1:9"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# One representative instrument per declared asset class, so symbol-driven
# paths run too (the default case lets the router inject its own default).
REPRESENTATIVE = {
    "EQUITY": "AAPL", "ETF": "SPY", "INDEX": "SPX", "CRYPTO": "BTCUSDT", "FX": "EURUSD",
    "BOND": "US10Y", "COMMODITY": "CL=F", "FUTURE": "ES=F", "OPTION": "AAPL",
}
# T2 rules that stay meaningful offline; freshness/as-of (amber), latency
# (T8) and input sensitivity (T3) need live data and belong to the live audit.
_KEEP_T2 = {"no_source", "fake_source", "live_claim_without_provider"}


@contextlib.contextmanager
def network_cut() -> Iterator[set[int]]:
    """Refuse every outbound connection for the duration of the block.

    DNS fails for every non-loopback name; a socket connect fails unless it
    targets a loopback port this process is itself listening on (asyncio's
    self-pipe on Windows is a loopback socket pair); and every HTTP stack that
    honours proxy variables (requests, httpx, aiohttp with trust_env, libcurl /
    curl_cffi under yfinance) is pointed at a dead local port, so even a
    resolver that bypasses ``socket.getaddrinfo`` cannot leave the machine.
    """
    listening: set[int] = set()
    orig = (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex, socket.socket.listen)
    saved_env = {k: os.environ.get(k) for k in (*_PROXY_VARS, "NO_PROXY", "no_proxy")}

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else host
        if name in (None, "") or str(name).lower() in _LOOPBACK:
            return orig[0](host, *args, **kwargs)
        raise socket.gaierror(socket.EAI_NONAME, f"offline audit: DNS disabled for {name}")

    def allowed(address: Any) -> bool:
        if isinstance(address, tuple) and len(address) >= 2:
            return str(address[0]).lower() in _LOOPBACK and address[1] in listening
        return True  # AF_UNIX and friends never leave the machine

    def connect(self: socket.socket, address: Any) -> Any:
        if not allowed(address):
            raise ConnectionRefusedError(errno.ECONNREFUSED, f"offline audit: connection to {address!r} refused")
        return orig[1](self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        return orig[2](self, address) if allowed(address) else errno.ECONNREFUSED

    def listen(self: socket.socket, *args: Any) -> Any:
        result = orig[3](self, *args)
        with contextlib.suppress(OSError):
            listening.add(self.getsockname()[1])
        return result

    # asyncio connects through loop.sock_connect, which on Windows' proactor
    # loop uses ConnectEx and never calls socket.connect (aiohttp with an
    # async resolver would otherwise leave the machine).
    import asyncio.proactor_events as proactor_events
    import asyncio.selector_events as selector_events

    loop_classes = (proactor_events.BaseProactorEventLoop, selector_events.BaseSelectorEventLoop)
    orig_sock_connect = {cls: cls.sock_connect for cls in loop_classes}

    def make_sock_connect(cls: type) -> Any:
        async def sock_connect(self: Any, sock: socket.socket, address: Any) -> Any:
            if not allowed(address):
                raise ConnectionRefusedError(errno.ECONNREFUSED,
                                             f"offline audit: connection to {address!r} refused")
            return await orig_sock_connect[cls](self, sock, address)

        return sock_connect

    for cls in loop_classes:
        cls.sock_connect = make_sock_connect(cls)  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.socket.listen = listen  # type: ignore[method-assign]
    for var in _PROXY_VARS:
        os.environ[var] = DEAD_PROXY
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = ""
    try:
        yield listening
    finally:
        socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex, socket.socket.listen = orig  # type: ignore[assignment]
        for cls, fn in orig_sock_connect.items():
            cls.sock_connect = fn  # type: ignore[method-assign]
        for var, value in saved_env.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value


def probe_cut(url: str = "https://example.com/") -> dict[str, str]:
    """Inside :func:`network_cut`: try every HTTP stack the adapters use.

    Returns ``{stack: "refused (...)" | "LEAK" | "not installed"}``.
    """
    results: dict[str, str] = {}

    def attempt(name: str, fn: Any) -> None:
        try:
            leaked = fn()
        except ImportError:
            results[name] = "not installed"
        except Exception as exc:  # noqa: BLE001 - any failure means the call was refused
            results[name] = f"refused ({type(exc).__name__})"
        else:
            results[name] = "LEAK" if leaked is not False else "refused (empty)"

    def _urllib() -> bool:
        import urllib.request

        urllib.request.urlopen(url, timeout=5).read(1)
        return True

    def _requests() -> bool:
        import requests

        requests.get(url, timeout=5)
        return True

    def _httpx() -> bool:
        import httpx

        httpx.get(url, timeout=5)
        return True

    def _curl() -> bool:
        from curl_cffi import requests as creq

        creq.get(url, timeout=5)
        return True

    def _aiohttp() -> bool:
        import asyncio

        import aiohttp

        async def go() -> None:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    await resp.read()

        asyncio.run(go())
        return True

    def _yfinance() -> bool:
        import yfinance as yf

        frame = yf.download("AAPL", period="5d", progress=False, threads=False)
        return frame is not None and not frame.empty

    for name, fn in (("urllib", _urllib), ("requests", _requests), ("httpx", _httpx), ("curl_cffi", _curl),
                     ("aiohttp", _aiohttp), ("yfinance", _yfinance)):
        attempt(name, fn)
    return results


def cases_for(entry: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = [("default", {})]
    for asset in entry.get("asset_classes") or []:
        symbol = REPRESENTATIVE.get(str(getattr(asset, "value", asset)).upper())
        if symbol:
            out.append((symbol, {"symbol": symbol}))
            break
    return out


def grade(code: str, category: str, params: dict[str, Any], http_status: int, body: Any, seconds: float,
          *, cfg: truth.TruthConfig, now: datetime, budget: float) -> list[truth.Finding]:
    out: list[truth.Finding] = []
    if http_status >= 500 or not isinstance(body, dict):
        out.append(truth.Finding("T10", "offline_crash", "red", f"HTTP {http_status}: {str(body)[:300]}"))
    else:
        out += truth.check_contract(body, http_status=http_status)
        if http_status < 400:
            out += [f for f in truth.check_provenance(body, code=code, category=category, cfg=cfg, now=now)
                    if f.rule in _KEEP_T2]
            out += truth.check_response_placeholders(body, request_params=params, cfg=cfg, code=code)
            out += truth.check_numeric_sanity(body, code=code, cfg=cfg, now=now)
            state = str(body.get("data_state") or "").lower()
            if str(body.get("status") or "").lower() == "ok" and state.startswith("live"):
                sources = body.get("sources") or body.get("source")
                out.append(truth.Finding("T10", "offline_live_claim", "red",
                                         f"data_state={state} with every connection refused (sources={sources})"))
    if isinstance(body, dict) and "timed out after" in str(body.get("reason") or ""):
        out.append(truth.Finding("T10", "offline_timeout", "amber",
                                 "hit the server timeout with the network cut instead of failing fast"))
    elif seconds > budget + 2.0:
        out.append(truth.Finding("T10", "offline_slow", "amber",
                                 f"{seconds:.1f}s with the network cut (budget {budget:.0f}s)"))
    return out


def run(codes: set[str] | None = None, *, budget: float = 8.0, workers: int = 8) -> dict[str, Any]:
    """Call every (or the given) function offline; return probe + per-case grades."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from showme import server
    from showme.audit import gate
    from showme.server_routes import AppDeps, function_index

    cfg = truth.load_config()
    now = datetime.now(timezone.utc)
    entries = [e for e in gate.catalog_entries() if not codes or str(e["code"]).upper() in codes]
    server.FUNCTION_TIMEOUT_SECONDS = budget
    functions: dict[str, list[dict[str, Any]]] = {}
    with network_cut():
        probe = probe_cut()
        app = FastAPI()
        function_index.register(app, AppDeps(boot_state={"engine_attached": True}))
        with TestClient(app) as client:

            def one(job: tuple[dict[str, Any], str, dict[str, Any]]) -> dict[str, Any]:
                entry, label, params = job
                code = str(entry["code"]).upper()
                t0 = time.perf_counter()
                try:
                    resp = client.post(f"/api/fn/{code}", json=params)
                    status = resp.status_code
                    try:
                        body: Any = resp.json()
                    except ValueError:
                        body = resp.text[:500]
                except Exception as exc:  # noqa: BLE001 - recorded as a crash
                    status, body = 599, f"{type(exc).__name__}: {exc}"
                seconds = time.perf_counter() - t0
                findings = grade(code, str(entry.get("category") or ""), params, status, body, seconds,
                                 cfg=cfg, now=now, budget=budget)
                return {
                    "code": code, "case": label, "params": params, "http_status": status,
                    "status": body.get("status") if isinstance(body, dict) else None,
                    "data_state": body.get("data_state") if isinstance(body, dict) else None,
                    "reason": str(body.get("reason") or "")[:240] if isinstance(body, dict) else None,
                    "seconds": round(seconds, 2), "findings": [f.to_dict() for f in findings],
                }

            jobs = [(e, label, p) for e in entries for label, p in cases_for(e)]
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for rec in pool.map(one, jobs):
                    functions.setdefault(rec["code"], []).append(rec)
    return {"generated_at": now.isoformat(), "budget_seconds": budget, "probe": probe,
            "functions": dict(sorted(functions.items()))}


def to_counts(report: dict[str, Any], *, severities: tuple[str, ...] = ("red",)) -> dict[str, dict[str, int]]:
    """Per-function counts for the ratchet. Only red findings by default:
    amber timing rules (offline_timeout / offline_slow) depend on machine
    load and would make the ratchet flaky; they stay in the report."""
    out: dict[str, dict[str, int]] = {}
    for code, cases in report["functions"].items():
        c = Counter(f"{f['check']}:{f['rule']}" for case in cases for f in case["findings"]
                    if f["severity"] in severities)
        if c:
            out[code] = dict(sorted(c.items()))
    return out


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict[str, int]] | None:
    return json.loads(path.read_text(encoding="utf-8"))["counts"] if path.exists() else None


def write_baseline(counts: dict[str, dict[str, int]], path: Path = BASELINE_PATH) -> None:
    doc = {
        "_doc": "Offline honesty ratchet (backend/showme/audit/offline.py): per function, count per "
                "'<check>:<rule>' with the network cut. Counts may only go down. Regenerate downward with "
                "SHOWME_UPDATE_OFFLINE_BASELINE=1 pytest tests/test_offline_honesty.py.",
        "total": sum(sum(r.values()) for r in counts.values()),
        "counts": counts,
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    counts = to_counts(report)
    reds = {code for code, cases in report["functions"].items()
            for case in cases for f in case["findings"] if f["severity"] == "red"}
    lines = [
        "# Offline honesty audit (T10)",
        "",
        f"Generated: {report['generated_at']} - every outbound connection refused, budget "
        f"{report['budget_seconds']:.0f}s per call. Network-cut probe: "
        + ", ".join(f"{k}={v}" for k, v in report["probe"].items()),
        "",
        f"- Functions called: {len(report['functions'])}; with a red finding: {len(reds)}; "
        f"with any finding: {len(counts)}",
        "",
        "| Code | Case | HTTP | status | data_state | s | Findings |",
        "|---|---|---:|---|---|---:|---|",
    ]
    for code, cases in report["functions"].items():
        for case in cases:
            fs = "; ".join(f"{f['check']}:{f['rule']} ({f['severity']}) {f['detail'][:90]}"
                           for f in case["findings"]).replace("|", "/")
            lines.append(f"| {code} | {case['case']} | {case['http_status']} | {case['status'] or '-'} | "
                         f"{case['data_state'] or '-'} | {case['seconds']} | {fs or 'clean'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--codes", default="", help="comma-separated codes (default: all)")
    ap.add_argument("--budget", type=float, default=8.0, help="per-call timeout in seconds")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--home", default="", help="SHOWME_HOME to use (default: a throw-away directory)")
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--md", dest="md_out", default="")
    args = ap.parse_args(argv)
    return _cli(args)


def _cli(args: argparse.Namespace) -> int:
    # Never run against the user's real app home: its bots, credentials and
    # portfolio must not be touched by an audit.
    if not args.home:
        args.home = tempfile.mkdtemp(prefix="showme-offline-")
    os.environ["SHOWME_HOME"] = args.home
    os.environ["SHOWME_DISABLE_BOTS"] = "1"
    codes = {c.strip().upper() for c in args.codes.split(",") if c.strip()} or None
    report = run(codes, budget=args.budget, workers=args.workers)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    if args.md_out:
        Path(args.md_out).write_text(render_markdown(report), encoding="utf-8")
    counts = to_counts(report)
    leaks = [k for k, v in report["probe"].items() if v == "LEAK"]
    print(f"functions={len(report['functions'])} with_findings={len(counts)} "
          f"findings={sum(sum(r.values()) for r in counts.values())} leaks={leaks}", file=sys.stderr)
    return 3 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
