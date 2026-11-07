#!/usr/bin/env python3
"""Strict truth audit runner (B1b) — ``showme_function_audit.py --strict``.

Runs every catalog function against a sidecar and grades it with the pure
checks in ``showme.audit.truth`` (T1-T8). Network access, sidecar restarts
and source lookup are injected so the orchestration is unit-tested without
a sidecar (``backend/tests/test_truth_audit_runner.py``).

Per case (function × primary asset):
  * call A (cold) with the audit's standard params (forced preview-only for
    anything ticket-shaped), call A again (warm latency), and — for
    symbol-taking functions — call B with the asset's second input from
    ``contracts/truth_audit.json:input_pairs`` (T3);
  * the request timeout is per function: twice its cold latency budget,
    capped by ``--timeout``;
  * a refused connection restarts the sidecar once and repeats the call;
    any other transient error is retried once; a persistent read timeout is
    a red T8 ``timeout`` (the local function was too slow), a persistent
    reset/abort is ``NETWORK_FLAKE`` (reported apart, never red).

Self-booted sidecars run with ``SHOWME_DISABLE_BOTS=1`` against a sandbox
copy of the app home (bots forced off, credential files left out), so an
audit can neither trade nor write into the user's data.

Output under ``artifacts/showme-truth-audit/<UTC>/``: ``ledger.json``,
``summary.md``, ``requests/`` and ``responses/`` plus ``ledger.partial.json``
after every case (``--resume <dir>``). ``--regrade <dir>`` re-grades a run's
saved responses with the current rules without calling any function.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from audit_functions import entry_uses_symbol, params_for, primary_assets, request_json

from showme.audit import gate, truth

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "artifacts" / "showme-truth-audit"
KEYLESS_PATH = ROOT / "contracts" / "keyless_alternatives.json"
NATIVE_CODES = {"AGENT", "ASK", "WATCH"}
GRADE_ORDER = {"RED": 4, "NETWORK_FLAKE": 3, "AMBER": 2, "GREEN": 1, "NOT_AUDITED": 0}
SANDBOX_SKIP = ("logs", "*.lock", "*credential*", "*secret*", "*.key", "*.pem", "keyring*")

RequestFn = Callable[[str, dict[str, Any], float], tuple[int, Any]]
SourceLookup = Callable[[str], "gate.Source | None"]


def safe_params(params: dict[str, Any]) -> dict[str, Any]:
    """Never let an audit call arm an order: preview-only, paper mode."""
    out = dict(params)
    if "submit" in out or "quantity" in out or "side" in out:
        out["submit"] = False
        out["paper_mode"] = True
    return out


def _unwrap(exc: BaseException) -> BaseException:
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        return exc.reason
    return exc


def is_transient(exc: BaseException) -> bool:
    """Errors worth one retry: timeouts and dropped/refused connections."""
    return isinstance(_unwrap(exc), (TimeoutError, ConnectionError))


_SERVER_TIMEOUT = re.compile(r"\btimed out after \d+(\.\d+)?s\b", re.I)


def server_timed_out(body: Any) -> bool:
    """The sidecar's own FUNCTION_TIMEOUT envelope (``provider_unavailable``)."""
    return (isinstance(body, dict) and str(body.get("status") or "").lower() == "provider_unavailable"
            and bool(_SERVER_TIMEOUT.search(str(body.get("reason") or ""))))


@dataclass
class Call:
    status: int
    body: Any
    error: str | None
    seconds: float
    timed_out: bool = False
    flake: bool = False


def grade_case(
    *,
    entry: dict[str, Any],
    asset: str | None,
    params: dict[str, Any],
    a: Call,
    warm: Call | None,
    b: Call | None,
    keyless_known: bool,
    cfg: truth.TruthConfig,
    now: datetime,
) -> dict[str, Any]:
    """Findings + grade for one case from its calls (live run and --regrade)."""
    code = str(entry.get("code", "")).upper()
    category = str(entry.get("category", ""))
    findings: list[truth.Finding] = []
    status = ""
    if a.error:
        if a.timed_out:
            findings += truth.check_latency(code, a.seconds, warm=False, cfg=cfg, timed_out=True)
        elif not a.flake:
            findings += truth.check_contract(None, error=a.error)
    else:
        body = a.body
        status = str(body.get("status") or "").lower() if isinstance(body, dict) else ""
        findings += truth.check_contract(body, http_status=a.status)
        if server_timed_out(body):
            findings += truth.check_latency(code, a.seconds, warm=False, cfg=cfg, timed_out=True)
        if isinstance(body, dict) and a.status < 400:
            findings += truth.check_provenance(body, code=code, category=category, cfg=cfg, now=now)
            findings += truth.check_response_placeholders(body, request_params=params, cfg=cfg, code=code)
            findings += truth.check_response_assets(body, requested_asset=asset, cfg=cfg)
            findings += truth.check_numeric_sanity(body, code=code, cfg=cfg, now=now)
            if warm is not None:
                if warm.error and not warm.timed_out:
                    findings.append(truth.Finding("T8", "warm_call_failed", "amber",
                                                  f"repeat call failed: {warm.error}"))
                else:
                    findings += truth.check_latency(code, warm.seconds, warm=True, cfg=cfg,
                                                    timed_out=warm.timed_out)
            if b is not None and code not in (cfg.raw.get("t3_skip") or {}):
                if b.error or not isinstance(b.body, dict):
                    findings.append(truth.Finding("T3", "second_input_failed", "amber",
                                                  f"call with the second input failed: {b.error or 'no body'}"))
                else:
                    findings += truth.check_input_sensitivity(body, b.body)
    return {
        "case_id": f"{code}-{asset or 'GLOBAL'}",
        "asset": asset or "GLOBAL",
        "grade": truth.grade(findings, status=status, keyless_alternative_known=keyless_known,
                             network_flake=a.flake),
        "status": status or None,
        "http_status": a.status,
        "error": a.error,
        "timed_out": a.timed_out,
        "flake": a.flake,
        "seconds_cold": round(a.seconds, 3),
        "seconds_warm": None if warm is None else round(warm.seconds, 3),
        "warm_error": None if warm is None else warm.error,
        "second_input": b is not None,
        "findings": [f.to_dict() for f in findings],
    }


class StrictRunner:
    def __init__(
        self,
        *,
        catalog: list[dict[str, Any]],
        request: RequestFn,
        restart: Callable[[], None],
        source_lookup: SourceLookup,
        keyless_alternatives: dict[str, Any],
        out_dir: Path,
        now: Callable[[], datetime] | None = None,
        cfg: truth.TruthConfig | None = None,
        timeout: float = 30.0,
        resume: bool = False,
        only: set[str] | None = None,
        log: Callable[[str], None] = lambda _msg: None,
    ) -> None:
        self.catalog = catalog
        self.request = request
        self.restart = restart
        self.source_lookup = source_lookup
        self.keyless = {k.upper() for k in keyless_alternatives}
        self.out_dir = Path(out_dir)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.cfg = cfg or truth.load_config()
        self.timeout_cap = timeout
        self.resume = resume
        self.only = {c.upper() for c in only} if only else None
        self.log = log
        self.partial_path = self.out_dir / "ledger.partial.json"
        self.done: dict[str, dict[str, Any]] = {}

    # ── I/O helpers ──────────────────────────────────────────────────────

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def timeout_for(self, code: str) -> float:
        budget = {**self.cfg.latency_budget_s, **self.cfg.latency_overrides.get(code.upper(), {})}
        return min(self.timeout_cap, 2.0 * float(budget["cold"]))

    def _call(self, code: str, params: dict[str, Any]) -> Call:
        retried = restarted = False
        timeout = self.timeout_for(code)
        while True:
            started = time.perf_counter()
            try:
                status, body = self.request(code, params, timeout)
                return Call(status, body, None, time.perf_counter() - started)
            except Exception as exc:  # noqa: BLE001 - classified below
                elapsed = time.perf_counter() - started
                inner = _unwrap(exc)
                if isinstance(inner, ConnectionRefusedError) and not restarted:
                    self.log(f"  sidecar refused {code}; restarting")
                    self.restart()
                    restarted = True
                    continue
                if is_transient(inner) and not retried:
                    retried = True
                    continue
                timed_out = isinstance(inner, TimeoutError)
                return Call(0, None, f"{type(inner).__name__}: {inner}", elapsed,
                            timed_out=timed_out, flake=is_transient(inner) and not timed_out)

    # ── per case ─────────────────────────────────────────────────────────

    def _case(self, entry: dict[str, Any], asset: str | None) -> dict[str, Any]:
        code = str(entry.get("code", "")).upper()
        case_id = f"{code}-{asset or 'GLOBAL'}"
        params = safe_params(params_for(entry, asset))
        self._write_json(self.out_dir / "requests" / f"{case_id}.json", params)
        a = self._call(code, params)
        stall = False
        if (a.timed_out or server_timed_out(a.body)) and not self._canary_ok():
            # Not this function's fault: the sidecar itself is stalled (or the
            # machine lost the network). Restart and give the case one more go.
            stall = True
            self.log(f"  {case_id}: canary failed too — sidecar stalled; restarting and retrying")
            self.restart()
            a = self._call(code, params)
        self._write_json(self.out_dir / "responses" / f"{case_id}.json", a.body)
        warm = b = None
        if not a.error and isinstance(a.body, dict) and a.status < 400:
            warm = self._call(code, params)
            if asset and entry_uses_symbol(entry) and code not in (self.cfg.raw.get("t3_skip") or {}):
                pair = self.cfg.input_pairs.get(asset.upper()) or []
                alt = next((s for s in pair if s != params.get("symbol")), None)
                if alt:
                    params_b = dict(params, symbol=alt)
                    if "topic" in params_b:
                        params_b["topic"] = alt
                    self._write_json(self.out_dir / "requests" / f"{case_id}-B.json", params_b)
                    b = self._call(code, params_b)
                    self._write_json(self.out_dir / "responses" / f"{case_id}-B.json", b.body)
        case = grade_case(entry=entry, asset=asset, params=params, a=a, warm=warm, b=b,
                          keyless_known=code in self.keyless, cfg=self.cfg, now=self.now())
        case["sidecar_stall_recovered"] = stall
        return case

    def _canary_ok(self) -> bool:
        canary = self.cfg.raw.get("canary") or {}
        code = canary.get("code")
        if not code:
            return True
        started = time.perf_counter()
        try:
            status, body = self.request(code, {}, float(canary.get("max_seconds", 5.0)) * 2)
        except Exception:  # noqa: BLE001
            return False
        fast = time.perf_counter() - started <= float(canary.get("max_seconds", 5.0))
        return fast and status < 400 and not server_timed_out(body)

    @staticmethod
    def function_grade(cases: list[dict[str, Any]], offline: list[dict[str, Any]]) -> str:
        grades = [c["grade"] for c in cases]
        if any(f["severity"] == "red" for f in offline):
            grades.append("RED")
        elif offline:
            grades.append("AMBER")
        return max(grades, key=lambda g: GRADE_ORDER[g]) if grades else "NOT_AUDITED"

    # ── main loop ────────────────────────────────────────────────────────

    def _entries(self) -> list[dict[str, Any]]:
        entries = sorted(self.catalog, key=lambda e: (str(e.get("category", "")), str(e.get("code", ""))))
        if self.only:
            entries = [e for e in entries if str(e.get("code", "")).upper() in self.only]
        return entries

    def run(self) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if self.resume and self.partial_path.exists():
            self.done = json.loads(self.partial_path.read_text(encoding="utf-8"))
        functions: dict[str, dict[str, Any]] = {}
        for entry in self._entries():
            code = str(entry.get("code", "")).upper()
            record: dict[str, Any] = {"name": entry.get("name", ""), "category": entry.get("category", "")}
            if code in NATIVE_CODES:
                record.update(grade="NOT_AUDITED", reason="native endpoint (not /api/fn); covered by the legacy audit",
                              cases=[], offline_findings=[])
                functions[code] = record
                continue
            offline = [f.to_dict() for f in gate.offline_findings_for(entry, self.source_lookup(code), self.cfg)]
            cases = []
            for asset in primary_assets(entry):
                case_id = f"{code}-{asset or 'GLOBAL'}"
                case = self.done.get(case_id)
                if case is None:
                    case = self._case(entry, asset)
                    self.done[case_id] = case
                    self._write_json(self.partial_path, self.done)
                    self.log(f"{case['grade']:<13} {case_id:<22} {case['seconds_cold']:>6.1f}s "
                             f"{', '.join(sorted({f['rule'] for f in case['findings']}))}")
                cases.append(case)
            record.update(grade=self.function_grade(cases, offline), cases=cases, offline_findings=offline)
            functions[code] = record
        return self._finish(functions)

    def _finish(self, functions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        ledger = {
            "generated_at": self.now().isoformat(),
            "counts": dict(Counter(r["grade"] for r in functions.values())),
            "functions": functions,
        }
        self._write_json(self.out_dir / "ledger.json", ledger)
        (self.out_dir / "summary.md").write_text(render_summary(ledger), encoding="utf-8")
        return ledger

    def regrade(self) -> dict[str, Any]:
        """Re-grade the saved requests/responses of this run with the current rules."""
        done = json.loads(self.partial_path.read_text(encoding="utf-8"))
        functions: dict[str, dict[str, Any]] = {}
        for entry in self._entries():
            code = str(entry.get("code", "")).upper()
            if code in NATIVE_CODES:
                functions[code] = {"name": entry.get("name", ""), "category": entry.get("category", ""),
                                   "grade": "NOT_AUDITED", "cases": [], "offline_findings": [],
                                   "reason": "native endpoint (not /api/fn); covered by the legacy audit"}
                continue
            offline = [f.to_dict() for f in gate.offline_findings_for(entry, self.source_lookup(code), self.cfg)]
            cases = []
            for asset in primary_assets(entry):
                case_id = f"{code}-{asset or 'GLOBAL'}"
                old = done.get(case_id)
                if old is None:
                    continue
                req = self._read(f"requests/{case_id}.json") or {}
                a = Call(old.get("http_status") or 0, self._read(f"responses/{case_id}.json"), old.get("error"),
                         old.get("seconds_cold") or 0.0, timed_out=bool(old.get("timed_out")),
                         flake=bool(old.get("flake")))
                warm = None
                if old.get("seconds_warm") is not None:
                    warm = Call(200, None, old.get("warm_error"), old["seconds_warm"],
                                timed_out=str(old.get("warm_error") or "").startswith("TimeoutError"))
                b = None
                if (self.out_dir / "responses" / f"{case_id}-B.json").exists():
                    body_b = self._read(f"responses/{case_id}-B.json")
                    b = Call(200 if body_b is not None else 0, body_b, None if body_b is not None else "no body", 0.0)
                cases.append(grade_case(entry=entry, asset=asset, params=req, a=a, warm=warm, b=b,
                                        keyless_known=code in self.keyless, cfg=self.cfg, now=self.now()))
            functions[code] = {"name": entry.get("name", ""), "category": entry.get("category", ""),
                               "grade": self.function_grade(cases, offline), "cases": cases,
                               "offline_findings": offline}
        return self._finish(functions)

    def _read(self, rel: str) -> Any:
        path = self.out_dir / rel
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _rules(rec: dict[str, Any], severity: str, *, checks: set[str] | None = None, exclude: set[str] = frozenset()) -> set[str]:
    out = set()
    for f in rec.get("offline_findings", []) + [f for c in rec.get("cases", []) for f in c["findings"]]:
        if f["severity"] == severity and (checks is None or f["check"] in checks) and f["check"] not in exclude:
            out.add(f["rule"])
    return out


def render_summary(ledger: dict[str, Any]) -> str:
    functions = ledger["functions"]
    lines = [
        "# Strict function truth audit",
        "",
        f"Generated: {ledger['generated_at']}",
        "",
        "Grades measure data truth (T1-T5, T7, T8 timeouts). Help-text debt (T6) is amber and",
        "listed in its own column; it never decides RED.",
        "",
        "| Grade | Functions |",
        "|---|---:|",
    ]
    for grade in ("GREEN", "AMBER", "RED", "NETWORK_FLAKE", "NOT_AUDITED"):
        lines.append(f"| {grade} | {ledger['counts'].get(grade, 0)} |")
    by_cat: dict[str, Counter] = {}
    for rec in functions.values():
        c = by_cat.setdefault(str(rec.get("category", "")), Counter())
        c[rec["grade"]] += 1
        if _rules(rec, "amber", checks={"T6"}):
            c["DOC"] += 1
    lines += ["", "## By category", "",
              "| Category | GREEN | AMBER | RED | FLAKE | N/A | Help-text debt |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for cat in sorted(by_cat):
        c = by_cat[cat]
        lines.append(f"| {cat} | {c['GREEN']} | {c['AMBER']} | {c['RED']} | {c['NETWORK_FLAKE']} "
                     f"| {c['NOT_AUDITED']} | {c['DOC']} |")
    rule_counts: Counter = Counter()
    for rec in functions.values():
        for f in rec.get("offline_findings", []) + [f for c in rec.get("cases", []) for f in c["findings"]]:
            rule_counts[(f["check"], f["rule"], f["severity"])] += 1
    lines += ["", "## Findings by rule", "", "| Check | Rule | Severity | Count |", "|---|---|---|---:|"]
    for (check, rule, sev), n in sorted(rule_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {check} | {rule} | {sev} | {n} |")
    lines += ["", "## RED functions", "", "| Code | Category | Red rules | Statuses |", "|---|---|---|---|"]
    for code, rec in sorted(functions.items()):
        if rec["grade"] != "RED":
            continue
        statuses = sorted({str(c["status"]) for c in rec.get("cases", []) if c.get("status")})
        lines.append(f"| {code} | {rec.get('category', '')} | {', '.join(sorted(_rules(rec, 'red'))) or '—'} "
                     f"| {', '.join(statuses) or '—'} |")
    return "\n".join(lines) + "\n"


# ── CLI glue (used by showme_function_audit.py --strict) ─────────────────


def sandbox_app_home(out_dir: Path) -> Path:
    """Copy the user's app home into the run directory (once) and return it.

    Functions see the real portfolio/watchlists, but whatever they write
    lands in the copy. Every bot in the copy is forced ``enabled=false`` and
    ``mode=shadow`` (belt and braces next to ``SHOWME_DISABLE_BOTS=1``), and
    credential-looking files are not copied.
    """
    from showme.app_paths import app_home

    target = out_dir / "app-home"
    if not target.exists():
        source = app_home()
        if source.exists():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(*SANDBOX_SKIP))
        else:
            target.mkdir(parents=True)
    disable_bots(target)
    return target


def disable_bots(home: Path) -> int:
    """Force every bot definition under ``home/bots`` off; return how many were changed."""
    changed = 0
    for path in sorted((home / "bots").glob("*.json")) if (home / "bots").is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink()  # unreadable bot file: drop it from the sandbox rather than risk it
            changed += 1
            continue
        items = data if isinstance(data, list) else data.get("bots", [data]) if isinstance(data, dict) else []
        for bot in items:
            if isinstance(bot, dict) and (bot.get("enabled") is not False or bot.get("mode") != "shadow"):
                bot["enabled"] = False
                bot["mode"] = "shadow"
                changed += 1
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return changed


def _catalog_and_lookup(base: str) -> tuple[list[dict[str, Any]], SourceLookup]:
    status, catalog = request_json(f"{base}/api/function-index", timeout=60)
    if status >= 400 or not isinstance(catalog, list):
        raise SystemExit(f"function-index failed: {status} {catalog}")
    sources, errors = gate.registry_sources()
    for module, error in errors.items():
        print(f"warning: {module}: {error}", flush=True)
    return catalog, sources.get


def run_cli(args: Any) -> int:
    from sidecar_smoke import start_sidecar, stop_sidecar, wait_healthy

    keyless = json.loads(KEYLESS_PATH.read_text(encoding="utf-8")) if KEYLESS_PATH.exists() else {}
    only = {c.strip().upper() for c in (args.only or "").split(",") if c.strip()} or None

    if getattr(args, "regrade", None):
        out_dir = Path(args.regrade)
        catalog = [e.model_dump() for e in __import__("showme.server", fromlist=["x"])._load_function_index()]
        sources, _errors = gate.registry_sources()
        runner = StrictRunner(catalog=catalog, request=lambda *a: (0, None), restart=lambda: None,
                              source_lookup=sources.get, keyless_alternatives=keyless, out_dir=out_dir,
                              only=only)
        ledger = runner.regrade()
        print(f"counts: {ledger['counts']}\nsummary: {out_dir / 'summary.md'}")
        return 0

    if args.resume:
        out_dir = Path(args.resume)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path(args.out_strict or DEFAULT_OUT) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {"proc": None, "base": (args.base_url or (f"http://127.0.0.1:{args.port}" if args.port else "")).rstrip("/")}

    def boot() -> None:
        if state["proc"] is not None:
            stop_sidecar(state["proc"])
            state["proc"] = None
        home = sandbox_app_home(out_dir)
        proc, port, _log = start_sidecar(extra_env={"SHOWME_HOME": str(home), "SHOWME_DISABLE_BOTS": "1"})
        state.update(proc=proc, base=f"http://127.0.0.1:{port}")
        wait_healthy(state["base"])
        print(f"sidecar {state['base']} (SHOWME_HOME={home}, bots disabled)", flush=True)

    def restart() -> None:
        if state["proc"] is None:
            raise SystemExit("sidecar at --base/--port refused the connection; restart it and use --resume")
        boot()

    try:
        if not state["base"]:
            boot()
        catalog, lookup = _catalog_and_lookup(state["base"])

        def request(code: str, params: dict[str, Any], timeout: float) -> tuple[int, Any]:
            return request_json(f"{state['base']}/api/fn/{urllib.parse.quote(code)}", params, timeout=timeout)

        runner = StrictRunner(
            catalog=catalog, request=request, restart=restart, source_lookup=lookup,
            keyless_alternatives=keyless, out_dir=out_dir, timeout=args.timeout, resume=bool(args.resume),
            only=only, log=lambda msg: print(msg, flush=True),
        )
        ledger = runner.run()
        print(f"counts: {ledger['counts']}")
        print(f"ledger: {out_dir / 'ledger.json'}")
        print(f"summary: {out_dir / 'summary.md'}")
        return 0
    finally:
        if state["proc"] is not None:
            stop_sidecar(state["proc"])
