#!/usr/bin/env python3
"""Strict truth audit runner (B1b) — ``showme_function_audit.py --strict``.

Runs every catalog function against a sidecar and grades it with the pure
checks in ``showme.audit.truth`` (T1-T8). Network access, sidecar restarts
and source lookup are injected so the orchestration is unit-tested without
a sidecar (``backend/tests/test_truth_audit_runner.py``).

Per case (function × primary asset):
  * call A (cold) with the audit's standard params, call A again (warm
    latency), and — for symbol-taking functions — call B with the asset's
    second input from ``contracts/truth_audit.json:input_pairs`` (T3);
  * a refused connection restarts the sidecar once and repeats the call;
  * any other transient error is retried once; a persistent read timeout
    is a red T8 ``timeout`` (the local function was too slow), a persistent
    reset/abort is ``NETWORK_FLAKE`` (reported apart, never red).

Output under ``artifacts/showme-truth-audit/<UTC>/``: ``ledger.json``,
``summary.md``, ``requests/`` and ``responses/``; progress is written to
``ledger.partial.json`` after every case so ``--resume <dir>`` continues.
"""
from __future__ import annotations

import inspect
import json
import os
import time
import urllib.error
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from audit_functions import entry_uses_symbol, params_for, primary_assets, request_json

from showme.audit import truth

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "artifacts" / "showme-truth-audit"
KEYLESS_PATH = ROOT / "contracts" / "keyless_alternatives.json"
NATIVE_CODES = {"AGENT", "ASK", "WATCH"}
GRADE_ORDER = {"RED": 4, "NETWORK_FLAKE": 3, "AMBER": 2, "GREEN": 1, "NOT_AUDITED": 0}

RequestFn = Callable[[str, dict[str, Any], float], tuple[int, Any]]


def _unwrap(exc: BaseException) -> BaseException:
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        return exc.reason
    return exc


def is_transient(exc: BaseException) -> bool:
    """Errors worth one retry: timeouts and dropped/refused connections."""
    return isinstance(_unwrap(exc), (TimeoutError, ConnectionError))


@dataclass
class Call:
    status: int
    body: Any
    error: str | None
    seconds: float
    timed_out: bool = False
    flake: bool = False


class StrictRunner:
    def __init__(
        self,
        *,
        catalog: list[dict[str, Any]],
        request: RequestFn,
        restart: Callable[[], None],
        source_lookup: Callable[[str], tuple[str, str] | None],
        keyless_alternatives: dict[str, Any],
        out_dir: Path,
        now: Callable[[], datetime] | None = None,
        cfg: truth.TruthConfig | None = None,
        timeout: float = 30.0,
        resume: bool = False,
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
        self.timeout = timeout
        self.resume = resume
        self.log = log
        self.partial_path = self.out_dir / "ledger.partial.json"
        self.done: dict[str, dict[str, Any]] = {}

    # ── I/O helpers ──────────────────────────────────────────────────────

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _call(self, code: str, params: dict[str, Any]) -> Call:
        retried = restarted = False
        while True:
            started = time.perf_counter()
            try:
                status, body = self.request(code, params, self.timeout)
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

    # ── grading ──────────────────────────────────────────────────────────

    def _offline_findings(self, entry: dict[str, Any]) -> list[truth.Finding]:
        code = str(entry.get("code", "")).upper()
        found = truth.check_catalog_entry_assets(entry) + truth.check_help_text(entry, cfg=self.cfg)
        source = self.source_lookup(code)
        if source is not None:
            text, filename = source
            found += truth.scan_source_placeholders(text, filename, cfg=self.cfg)
        return found

    def _case(self, entry: dict[str, Any], asset: str | None) -> dict[str, Any]:
        code = str(entry.get("code", "")).upper()
        category = str(entry.get("category", ""))
        case_id = f"{code}-{asset or 'GLOBAL'}"
        params = params_for(entry, asset)
        self._write_json(self.out_dir / "requests" / f"{case_id}.json", params)
        a = self._call(code, params)
        self._write_json(self.out_dir / "responses" / f"{case_id}.json", a.body)
        findings: list[truth.Finding] = []
        status = ""
        warm_seconds: float | None = None
        if a.error:
            if a.timed_out:
                findings += truth.check_latency(code, a.seconds, warm=False, cfg=self.cfg, timed_out=True)
            elif not a.flake:
                findings += truth.check_contract(None, error=a.error)
        else:
            body = a.body
            status = str(body.get("status") or "").lower() if isinstance(body, dict) else ""
            findings += truth.check_contract(body, http_status=a.status)
            if isinstance(body, dict) and a.status < 400:
                now = self.now()
                findings += truth.check_provenance(body, code=code, category=category, cfg=self.cfg, now=now)
                findings += truth.check_response_placeholders(body, request_params=params, cfg=self.cfg)
                findings += truth.check_response_assets(body, requested_asset=asset, cfg=self.cfg)
                findings += truth.check_numeric_sanity(body, code=code, cfg=self.cfg, now=now)
                warm = self._call(code, params)
                warm_seconds = warm.seconds
                findings += truth.check_latency(code, warm.seconds, warm=True, cfg=self.cfg,
                                                timed_out=warm.timed_out)
                if asset and entry_uses_symbol(entry):
                    pair = self.cfg.input_pairs.get(asset.upper()) or []
                    alt = next((s for s in pair if s != params.get("symbol")), None)
                    if alt:
                        params_b = dict(params, symbol=alt)
                        if "topic" in params_b:
                            params_b["topic"] = alt
                        b = self._call(code, params_b)
                        self._write_json(self.out_dir / "responses" / f"{case_id}-B.json", b.body)
                        if not b.error:
                            findings += truth.check_input_sensitivity(body, b.body)
        grade = truth.grade(findings, status=status, keyless_alternative_known=code in self.keyless,
                            network_flake=a.flake)
        return {
            "case_id": case_id,
            "asset": asset or "GLOBAL",
            "grade": grade,
            "status": status or None,
            "http_status": a.status,
            "error": a.error,
            "seconds_cold": round(a.seconds, 3),
            "seconds_warm": None if warm_seconds is None else round(warm_seconds, 3),
            "findings": [f.to_dict() for f in findings],
        }

    @staticmethod
    def _function_grade(cases: list[dict[str, Any]], offline: list[truth.Finding]) -> str:
        grades = [c["grade"] for c in cases]
        if any(f.severity == "red" for f in offline):
            grades.append("RED")
        elif offline:
            grades.append("AMBER")
        return max(grades, key=lambda g: GRADE_ORDER[g]) if grades else "NOT_AUDITED"

    # ── main loop ────────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if self.resume and self.partial_path.exists():
            self.done = json.loads(self.partial_path.read_text(encoding="utf-8"))
        functions: dict[str, dict[str, Any]] = {}
        for entry in sorted(self.catalog, key=lambda e: (str(e.get("category", "")), str(e.get("code", "")))):
            code = str(entry.get("code", "")).upper()
            record: dict[str, Any] = {"name": entry.get("name", ""), "category": entry.get("category", "")}
            if code in NATIVE_CODES:
                record.update(grade="NOT_AUDITED", reason="native endpoint (not /api/fn); covered by the legacy audit",
                              cases=[], offline_findings=[])
                functions[code] = record
                continue
            offline = self._offline_findings(entry)
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
            record.update(grade=self._function_grade(cases, offline), cases=cases,
                          offline_findings=[f.to_dict() for f in offline])
            functions[code] = record
        ledger = {
            "generated_at": self.now().isoformat(),
            "counts": dict(Counter(r["grade"] for r in functions.values())),
            "functions": functions,
        }
        self._write_json(self.out_dir / "ledger.json", ledger)
        (self.out_dir / "summary.md").write_text(render_summary(ledger), encoding="utf-8")
        return ledger


def render_summary(ledger: dict[str, Any]) -> str:
    functions = ledger["functions"]
    lines = [
        "# Strict function truth audit",
        "",
        f"Generated: {ledger['generated_at']}",
        "",
        "| Grade | Functions |",
        "|---|---:|",
    ]
    for grade in ("GREEN", "AMBER", "RED", "NETWORK_FLAKE", "NOT_AUDITED"):
        lines.append(f"| {grade} | {ledger['counts'].get(grade, 0)} |")
    by_cat: dict[str, Counter] = {}
    for rec in functions.values():
        by_cat.setdefault(str(rec.get("category", "")), Counter())[rec["grade"]] += 1
    lines += ["", "## By category", "", "| Category | GREEN | AMBER | RED | FLAKE | N/A |", "|---|---:|---:|---:|---:|---:|"]
    for cat in sorted(by_cat):
        c = by_cat[cat]
        lines.append(f"| {cat} | {c['GREEN']} | {c['AMBER']} | {c['RED']} | {c['NETWORK_FLAKE']} | {c['NOT_AUDITED']} |")
    rule_counts: Counter = Counter()
    for rec in functions.values():
        for f in rec.get("offline_findings", []):
            rule_counts[(f["check"], f["rule"], f["severity"])] += 1
        for case in rec.get("cases", []):
            for f in case["findings"]:
                rule_counts[(f["check"], f["rule"], f["severity"])] += 1
    lines += ["", "## Findings by rule", "", "| Check | Rule | Severity | Count |", "|---|---|---|---:|"]
    for (check, rule, sev), n in sorted(rule_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {check} | {rule} | {sev} | {n} |")
    lines += ["", "## RED functions", "", "| Code | Category | Rules |", "|---|---|---|"]
    for code, rec in sorted(functions.items()):
        if rec["grade"] != "RED":
            continue
        rules = sorted({f["rule"] for f in rec.get("offline_findings", []) if f["severity"] == "red"}
                       | {f["rule"] for c in rec.get("cases", []) for f in c["findings"] if f["severity"] == "red"}
                       | ({"status:" + str(c["status"]) for c in rec.get("cases", [])
                           if c["status"] in {"calc_error", "input_error"}}))
        lines.append(f"| {code} | {rec.get('category', '')} | {', '.join(rules)} |")
    return "\n".join(lines) + "\n"


# ── CLI glue (used by showme_function_audit.py --strict) ─────────────────


def registry_source_lookup() -> Callable[[str], tuple[str, str] | None]:
    import importlib
    import pkgutil

    import showme.engine.functions as functions_pkg
    from showme.engine.core.base_function import FunctionRegistry

    for mod in pkgutil.walk_packages(functions_pkg.__path__, functions_pkg.__name__ + "."):
        try:
            importlib.import_module(mod.name)
        except Exception:  # noqa: BLE001 - a broken module is reported by the live call
            pass
    files: dict[str, tuple[str, str]] = {}
    for code, cls in FunctionRegistry._instances.items():
        try:
            path = Path(inspect.getsourcefile(cls) or "")
            files[code.upper()] = (path.read_text(encoding="utf-8"), path.name)
        except (OSError, TypeError):
            continue
    return files.get


def run_cli(args: Any) -> int:
    from sidecar_smoke import start_sidecar, stop_sidecar, wait_healthy

    state: dict[str, Any] = {"proc": None, "base": (args.base_url or (f"http://127.0.0.1:{args.port}" if args.port else "")).rstrip("/")}

    def boot() -> None:
        if state["proc"] is not None:
            stop_sidecar(state["proc"])
        proc, port, _log = start_sidecar()
        state.update(proc=proc, base=f"http://127.0.0.1:{port}")
        wait_healthy(state["base"])

    def restart() -> None:
        if state["proc"] is None:
            raise SystemExit("sidecar at --base/--port refused the connection; restart it and use --resume")
        boot()

    if not state["base"]:
        boot()
    try:
        status, catalog = request_json(f"{state['base']}/api/function-index", timeout=60)
        if status >= 400 or not isinstance(catalog, list):
            raise SystemExit(f"function-index failed: {status} {catalog}")
        keyless = json.loads(KEYLESS_PATH.read_text(encoding="utf-8")) if KEYLESS_PATH.exists() else {}
        if args.resume:
            out_dir = Path(args.resume)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out_dir = Path(args.out_strict or DEFAULT_OUT) / stamp

        def request(code: str, params: dict[str, Any], timeout: float) -> tuple[int, Any]:
            return request_json(f"{state['base']}/api/fn/{urllib.parse.quote(code)}", params, timeout=timeout)

        runner = StrictRunner(
            catalog=catalog, request=request, restart=restart, source_lookup=registry_source_lookup(),
            keyless_alternatives=keyless, out_dir=out_dir, timeout=args.timeout, resume=bool(args.resume),
            log=lambda msg: print(msg, flush=True),
        )
        ledger = runner.run()
        print(f"counts: {ledger['counts']}")
        print(f"ledger: {out_dir / 'ledger.json'}")
        print(f"summary: {out_dir / 'summary.md'}")
        return 0
    finally:
        if state["proc"] is not None:
            stop_sidecar(state["proc"])
