"""Strict truth checks for ``/api/fn/<code>`` responses (B1, checks T1-T8).

Pure functions: every check takes plain data (a response body, a catalog
entry, source text, a duration) and returns a list of :class:`Finding`.
Nothing here does I/O except :func:`load_config`, which reads the data
tables in ``contracts/truth_audit.json``. Orchestration (running functions
against a live sidecar, writing the ledger) lives in
``scripts/showme_function_audit.py --strict``; the offline ratchet lives in
``backend/tests/test_function_truth_gate.py``.

Spec: docs/superpowers/specs/2026-11-07-foundation-and-function-audit-design.md §2.

Severity: ``red`` = the function shows something untrue or is broken;
``amber`` = a weakness that is not by itself a lie (a placeholder default
in code, a slow call, missing/template help text). Help-text (T6) findings
are documentation debt: amber, reported in their own column, and ratcheted
by the offline gate — they never mask or inflate the data-truth grade.
"""
from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "contracts" / "truth_audit.json"

ALLOWED_STATUSES = {"ok", "empty", "input_error", "provider_unavailable", "calc_error"}
SENTINEL_TEXTS = (
    "No rows",
    "No ratios",
    "function did not return",
    "undefined",
    "null table",
    "NONE source",
)
# Parts of a response that carry the function's actual output.
PAYLOAD_KEYS = ("rows", "series", "cards", "payload", "data")
# Keys that legitimately vary between runs or echo the request.
VOLATILE_KEYS = {
    "asof", "as_of", "fetched_at", "elapsed_ms", "generated_at", "retrieved_at",
    "date", "time", "timestamp", "ts", "datetime", "period", "updated_at",
    "inputecho", "instrument", "symbol", "ticker", "pair", "sourcedetails",
}
DATE_KEYS = {"date", "time", "timestamp", "ts", "datetime", "as_of", "asof", "period", "period_end"}
GENERIC_INPUTS = {"symbol", "query/params when needed", "local portfolio state"}
_CURRENCIES = {"USD", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD", "TRY", "CNY", "SEK", "NOK", "MXN", "ZAR"}
_VOL_KEY = re.compile(r"(^|_)(vol|volatility|sigma|stdev|std)($|_)", re.I)
_PROB_KEY = re.compile(r"(^|_)(prob|probability|pd)($|_)", re.I)
_PCT_KEY = re.compile(r"pct|percent", re.I)
_DAILY_RETURN_KEYS = {"daily_return", "ret_1d", "return_1d"}
_WEIGHT_KEYS = {"weight", "target_weight"}
_PARAM_CONTAINERS = {"params", "kwargs", "inputs", "opts", "options", "config", "cfg"}


@dataclass(frozen=True)
class Finding:
    check: str
    rule: str
    severity: str  # "red" | "amber"
    detail: str
    location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TruthConfig:
    max_age_days: dict[str, float]
    cadence_by_category: dict[str, str]
    cadence_overrides: dict[str, str]
    calendar_codes: set[str]
    latency_budget_s: dict[str, float]
    latency_overrides: dict[str, dict[str, float]]
    fake_source_names: set[str]
    fake_source_substrings: tuple[str, ...]
    computed_source_names: set[str]
    # (key pattern, values, why, scopes) — scopes ⊆ {"source", "response"}
    placeholder_rules: list[tuple[re.Pattern[str], tuple[Any, ...], str, frozenset[str]]]
    crypto_demo_universe: set[str]
    template_patterns: list[re.Pattern[str]]
    input_pairs: dict[str, list[str]]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def load_config(path: Path | str | None = None) -> TruthConfig:
    raw = json.loads(Path(path or DEFAULT_CONFIG_PATH).read_text(encoding="utf-8"))
    return TruthConfig(
        max_age_days={k: float(v) for k, v in raw["max_age_days"].items()},
        cadence_by_category=dict(raw["cadence_by_category"]),
        cadence_overrides={k.upper(): v for k, v in raw.get("cadence_overrides", {}).items()},
        calendar_codes={c.upper() for c in raw.get("calendar_codes", [])},
        latency_budget_s={k: float(v) for k, v in raw["latency_budget_s"].items()},
        latency_overrides={k.upper(): v for k, v in raw.get("latency_overrides", {}).items()},
        fake_source_names={s.upper() for s in raw.get("fake_source_names", [])},
        fake_source_substrings=tuple(s.lower() for s in raw.get("fake_source_substrings", [])),
        computed_source_names={s.lower() for s in raw.get("computed_source_names", [])},
        placeholder_rules=[
            (re.compile(r["key"], re.I), tuple(r["values"]), r.get("why", ""),
             frozenset(r.get("scope", ["source", "response"])))
            for r in raw.get("placeholder_values", [])
        ],
        crypto_demo_universe={s.upper() for s in raw.get("crypto_demo_universe", [])},
        template_patterns=[re.compile(p, re.I) for p in raw.get("template_help_patterns", [])],
        input_pairs={k.upper(): list(v) for k, v in raw.get("input_pairs", {}).items()},
        raw=raw,
    )


# ── helpers ───────────────────────────────────────────────────────────────


def _walk(obj: Any, path: str = "") -> Iterator[tuple[str | None, Any, str]]:
    """Yield ``(key, leaf_value, path)`` for every scalar leaf."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if isinstance(v, (dict, list)):
                yield from _walk(v, p)
            else:
                yield str(k), v, p
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]"
            if isinstance(v, (dict, list)):
                yield from _walk(v, p)
            else:
                yield None, v, p


def _payload_leaves(body: dict[str, Any]) -> Iterator[tuple[str | None, Any, str]]:
    for key in PAYLOAD_KEYS:
        part = body.get(key)
        if isinstance(part, (dict, list)):
            yield from _walk(part, key)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _finite(v: Any) -> bool:
    """``math.isfinite`` without OverflowError on huge ints (ints are always finite)."""
    return isinstance(v, int) or math.isfinite(v)


def _status(body: dict[str, Any]) -> str:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    return str(body.get("status") or data.get("status") or "").lower()


def _parse_when(value: Any) -> datetime | None:
    if _is_number(value) and _finite(value):
        if 1e12 <= value < 1e14:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        if 1e9 <= value < 1e11:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return None
    if isinstance(value, str):
        quarter = re.fullmatch(r"\s*(\d{4})-?Q([1-4])\s*", value, re.I)
        if quarter:  # period end of the quarter
            year, q = int(quarter.group(1)), int(quarter.group(2))
            return datetime(year, 3 * q, 1, tzinfo=timezone.utc) + timedelta(days=31 if q in (1, 4) else 30) - timedelta(days=1)
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}(-\d{2})?", value.strip()):
        text = value.strip().replace("Z", "+00:00")
        if re.fullmatch(r"\d{4}-\d{2}", text):
            text += "-01"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text[:10])
            except ValueError:
                return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _payload_dates(body: dict[str, Any]) -> list[tuple[datetime, str]]:
    out = []
    for key, value, path in _payload_leaves(body):
        if key is not None and key.lower() in DATE_KEYS:
            when = _parse_when(value)
            if when is not None:
                out.append((when, path))
    return out


def _source_names(body: dict[str, Any]) -> list[str]:
    names: list[str] = []
    raw_sources = body.get("sources") or []
    if isinstance(raw_sources, str):
        raw_sources = [raw_sources]
    for s in raw_sources if isinstance(raw_sources, list) else []:
        if isinstance(s, str) and s.strip():
            names.append(s.strip())
    details = body.get("sourceDetails")
    for d in details if isinstance(details, list) else []:
        if isinstance(d, dict) and isinstance(d.get("name"), str) and d["name"].strip():
            names.append(d["name"].strip())
    return list(dict.fromkeys(names))


def infer_asset_class(symbol: str | None) -> str | None:
    """Conservative symbol → asset class guess; ``None`` when unsure."""
    if not symbol:
        return None
    s = symbol.strip().upper()
    if s.endswith(("USDT", "USDC", "-USD")):
        return "CRYPTO"
    if s.endswith("=F"):
        return "COMMODITY"
    if s.startswith("^"):
        return "INDEX"
    if re.fullmatch(r"[A-Z]{2}\d{1,2}Y", s):
        return "BOND"
    core = s[:-2] if s.endswith("=X") else s
    if re.fullmatch(r"[A-Z]{6}", core) and core[:3] in _CURRENCIES and core[3:] in _CURRENCIES:
        return "FX"
    return None


# ── T1 contract ───────────────────────────────────────────────────────────


def check_contract(body: Any, *, http_status: int = 200, error: str | None = None) -> list[Finding]:
    if error:
        return [Finding("T1", "request_error", "red", error)]
    if http_status >= 400:
        return [Finding("T1", "http_error", "red", f"http {http_status}: {str(body)[:200]}")]
    if not isinstance(body, dict):
        return [Finding("T1", "not_json_object", "red", f"response is {type(body).__name__}")]
    out: list[Finding] = []
    status = _status(body)
    if status not in ALLOWED_STATUSES:
        out.append(Finding("T1", "invalid_status", "red", f"status={status or '<missing>'}"))
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    if status in ALLOWED_STATUSES - {"ok"}:
        if not str(body.get("reason") or data.get("reason") or "").strip():
            out.append(Finding("T1", "missing_reason", "red", f"{status} without reason"))
        if not (body.get("nextAction") or data.get("nextAction")
                or body.get("next_actions") or data.get("next_actions")):
            out.append(Finding("T1", "missing_next_action", "red", f"{status} without nextAction"))
    for key, value, path in _payload_leaves(body):
        if isinstance(value, str):
            for sentinel in SENTINEL_TEXTS:
                if sentinel in value:
                    out.append(Finding("T1", "sentinel_text", "red", f"{sentinel!r} in payload", path))
                    break
    return out


# ── T2 provenance / freshness ─────────────────────────────────────────────


def check_provenance(
    body: dict[str, Any], *, code: str, category: str, cfg: TruthConfig, now: datetime
) -> list[Finding]:
    if _status(body) != "ok":
        return []
    out: list[Finding] = []
    names = _source_names(body)
    if not names:
        out.append(Finding("T2", "no_source", "red", "ok response names no source"))
    for name in names:
        lowered = name.lower()
        if name.upper() in cfg.fake_source_names or any(s in lowered for s in cfg.fake_source_substrings):
            out.append(Finding("T2", "fake_source", "red", f"source {name!r} is not a real provider"))
    state = str(body.get("data_state") or "").lower()
    if names and state == "live" and all(n.lower() in cfg.computed_source_names for n in names):
        out.append(Finding("T2", "live_claim_without_provider", "red",
                           f"data_state=live but sources are computed only: {names}"))
    if not (body.get("asOf") or body.get("as_of")):
        out.append(Finding("T2", "missing_as_of", "amber", "no asOf on an ok response"))
    code_u = code.upper()
    cadence = cfg.cadence_overrides.get(code_u) or cfg.cadence_by_category.get(category.lower())
    if cadence and code_u not in cfg.calendar_codes:
        dates = _payload_dates(body)
        if dates:
            latest, path = max(dates, key=lambda d: d[0])
            limit = timedelta(days=cfg.max_age_days[cadence])
            if now - latest > limit:
                age = (now - latest).days
                out.append(Finding("T2", "stale_data", "red",
                                   f"newest {cadence} datapoint is {age}d old (limit {limit.days}d)", path))
    return out


# ── T3 input sensitivity ──────────────────────────────────────────────────


def _fingerprint(body: dict[str, Any]) -> list[tuple[str, float]]:
    out = []
    for key, value, path in _payload_leaves(body):
        if key is not None and key.lower() in VOLATILE_KEYS:
            continue
        if any(part.lower() in VOLATILE_KEYS for part in re.split(r"[.\[\]]", path) if part):
            continue
        if _is_number(value) and _finite(value):
            out.append((path, value if isinstance(value, int) else round(float(value), 9)))
    return out


def check_input_sensitivity(body_a: Any, body_b: Any) -> list[Finding]:
    """Two runs with different primary inputs must not return identical numbers."""
    if not (isinstance(body_a, dict) and isinstance(body_b, dict)):
        return []
    if _status(body_a) != "ok" or _status(body_b) != "ok":
        return []
    fa, fb = _fingerprint(body_a), _fingerprint(body_b)
    if len(fa) >= 3 and fa == fb:
        return [Finding("T3", "static_output", "red",
                        f"{len(fa)} numeric values identical for two different inputs")]
    return []


# ── T4 placeholder fingerprints ───────────────────────────────────────────


def _value_matches(value: Any, candidates: tuple[Any, ...]) -> bool:
    for c in candidates:
        if isinstance(c, str):
            if isinstance(value, str) and value == c:
                return True
        elif _is_number(value) and _is_number(c) and _finite(value) and value == c:
            return True
    return False


def _norm(value: Any) -> Any:
    if _is_number(value) and not isinstance(value, int) and math.isfinite(value) and float(value).is_integer():
        return int(value)  # 10000.0 and 10000 are the same requested value
    return value


def check_response_placeholders(
    body: dict[str, Any], *, request_params: dict[str, Any], cfg: TruthConfig
) -> list[Finding]:
    requested = {(k.lower(), _norm(v)) for k, v, _ in _walk(request_params or {}) if k is not None}
    out: list[Finding] = []
    seen: set[tuple[str, Any]] = set()  # rows/cards/data often repeat the same value
    for key, value, path in _payload_leaves(body):
        if key is None:
            continue
        pair = (key.lower(), _norm(value))
        if pair in requested or pair in seen:
            continue
        for pattern, values, why, scopes in cfg.placeholder_rules:
            if "response" in scopes and pattern.search(key) and _value_matches(value, values):
                seen.add(pair)
                out.append(Finding("T4", "placeholder_value", "red",
                                   f"{key}={value!r} looks like a {why} the request did not supply", path))
                break
    req_asset = str((request_params or {}).get("asset_class") or "").upper() or infer_asset_class(
        str((request_params or {}).get("symbol") or ""))
    if req_asset and req_asset != "CRYPTO":
        symbols = [str(v).upper() for k, v, _ in _payload_leaves(body) if k == "symbol" and isinstance(v, str)]
        if len(symbols) >= 2 and all(s in cfg.crypto_demo_universe for s in symbols):
            out.append(Finding("T4", "demo_universe", "red",
                               f"{req_asset} request answered with the crypto demo universe {sorted(set(symbols))}"))
    return out


def _const(node: ast.AST | None) -> tuple[bool, Any]:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        return True, node.value
    return False, None


def scan_source_placeholders(
    source: str, filename: str, *, cfg: TruthConfig, class_name: str | None = None
) -> list[Finding]:
    """AST scan for placeholder defaults (``account=10_000``, ``.get("strike", 105)`` ...).

    With ``class_name`` the scan covers that class plus module-level code
    (shared helpers) but skips the bodies of *other* top-level classes, so a
    module holding several functions does not charge one function's
    defaults to its neighbours.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding("T4", "unparseable_source", "amber", str(exc), filename)]
    out: list[Finding] = []
    foreign = [
        (node.lineno, node.end_lineno or node.lineno)
        for node in tree.body
        if isinstance(node, ast.ClassDef) and class_name is not None and node.name != class_name
    ]

    def hit(name: str | None, node: ast.AST | None) -> None:
        ok, value = _const(node)
        if not ok or not name:
            return
        line = getattr(node, "lineno", 0)
        if any(start <= line <= end for start, end in foreign):
            return
        for pattern, values, why, scopes in cfg.placeholder_rules:
            if "source" in scopes and pattern.search(name) and _value_matches(value, values):
                out.append(Finding("T4", "placeholder_default", "amber",
                                   f"{name}={value!r} ({why}) hard-coded as a default",
                                   f"{filename}:{getattr(node, 'lineno', '?')}"))
                return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = node.args.posonlyargs + node.args.args
            for arg, default in zip(positional[len(positional) - len(node.args.defaults):], node.args.defaults):
                hit(arg.arg, default)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                hit(arg.arg, default)
        elif isinstance(node, ast.Call):
            func = node.func
            # Only request-parameter lookups: ``params.get("spot", 100)`` invents
            # an input; ``slot.get("qty", 0.0)`` merely parses a data record.
            if (isinstance(func, ast.Attribute) and func.attr in {"get", "pop", "setdefault"}
                    and isinstance(func.value, ast.Name) and func.value.id in _PARAM_CONTAINERS
                    and len(node.args) >= 2):
                ok, key = _const(node.args[0])
                if ok and isinstance(key, str):
                    hit(key, node.args[1])
            for kw in node.keywords:
                hit(kw.arg, kw.value)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                ok, key = _const(k)
                if ok and isinstance(key, str):
                    hit(key, v)
        # Plain assignments (``qty = 0.0``) are deliberately not scanned:
        # they are overwhelmingly accumulator initialisers, not inputs.
    return out


# ── T5 asset compatibility ────────────────────────────────────────────────


def _declared_classes(entry: dict[str, Any]) -> set[str]:
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    classes = entry.get("asset_classes") or usage.get("asset_classes") or []
    return {str(c).upper() for c in classes}


def check_catalog_entry_assets(entry: dict[str, Any]) -> list[Finding]:
    classes = _declared_classes(entry)
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    example = usage.get("example") if isinstance(usage.get("example"), dict) else {}
    if not classes or not example:
        return []
    out: list[Finding] = []
    ex_asset = str(example.get("asset_class") or "").upper()
    if ex_asset and ex_asset not in classes:
        out.append(Finding("T5", "example_asset_mismatch", "red",
                           f"default example asset_class {ex_asset} not in declared {sorted(classes)}"))
    inferred = infer_asset_class(example.get("symbol"))
    if inferred and inferred not in classes and inferred != ex_asset:
        out.append(Finding("T5", "example_asset_mismatch", "red",
                           f"default example symbol {example.get('symbol')!r} looks {inferred}, "
                           f"not in declared {sorted(classes)}"))
    return out


def check_response_assets(body: dict[str, Any], *, requested_asset: str | None, cfg: TruthConfig) -> list[Finding]:
    out: list[Finding] = []
    status = _status(body)
    reason = str(body.get("reason") or "")
    if status == "input_error" and re.search(r"does not support", reason, re.I):
        out.append(Finding("T5", "asset_not_supported", "red", reason[:200]))
    instrument = body.get("instrument") if isinstance(body.get("instrument"), dict) else {}
    got = str(instrument.get("asset_class") or "").upper()
    if requested_asset and got and got != requested_asset.upper():
        out.append(Finding("T5", "response_asset_mismatch", "red",
                           f"requested {requested_asset.upper()}, response instrument says {got}"))
    return out


# ── T6 help text ──────────────────────────────────────────────────────────


def check_help_text(entry: dict[str, Any], *, cfg: TruthConfig) -> list[Finding]:
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    description = str(entry.get("description") or "").strip()
    purpose = str(usage.get("purpose") or "").strip()
    out: list[Finding] = []
    if not description:
        out.append(Finding("T6", "empty_description", "amber", "catalog description is empty"))
    elif any(p.search(description) for p in cfg.template_patterns):
        out.append(Finding("T6", "template_description", "amber", f"template description: {description[:120]!r}"))
    if not purpose or any(p.search(purpose) for p in cfg.template_patterns):
        out.append(Finding("T6", "template_purpose", "amber", f"template purpose: {purpose[:120]!r}"))
    inputs = [str(i).strip().lower() for i in usage.get("inputs") or []]
    if not inputs or set(inputs) <= GENERIC_INPUTS:
        out.append(Finding("T6", "generic_inputs", "amber", f"inputs documented as {inputs}"))
    return out


# ── T7 numeric sanity ─────────────────────────────────────────────────────


def check_numeric_sanity(body: dict[str, Any], *, code: str, cfg: TruthConfig, now: datetime) -> list[Finding]:
    out: list[Finding] = []
    for key, value, path in _payload_leaves(body):
        if not _is_number(value):
            continue
        if not _finite(value):
            out.append(Finding("T7", "non_finite", "red", f"{key or 'value'}={value}", path))
            continue
        if key is None:
            continue
        if _VOL_KEY.search(key) and value < 0:
            out.append(Finding("T7", "negative_volatility", "red", f"{key}={value}", path))
        if _PROB_KEY.search(key):
            upper = 100.0 if _PCT_KEY.search(key) else 1.0
            if not 0.0 <= value <= upper:
                out.append(Finding("T7", "probability_out_of_range", "red", f"{key}={value} not in [0,{upper:g}]", path))
        if key.lower() in _DAILY_RETURN_KEYS and abs(value) >= 1.0:
            out.append(Finding("T7", "implausible_daily_return", "red", f"{key}={value}", path))
    rows = body.get("rows") if isinstance(body.get("rows"), list) else []
    weights = [r[k] for r in rows if isinstance(r, dict) for k in _WEIGHT_KEYS if _is_number(r.get(k))]
    if len(weights) >= 2 and all(w >= 0 for w in weights):
        total = sum(weights)
        if abs(total - 1.0) > 1e-3 and abs(total - 100.0) > 0.1:
            out.append(Finding("T7", "weights_not_normalized", "amber", f"long-only weights sum to {total:.6g}"))
    if code.upper() not in cfg.calendar_codes:
        for when, path in _payload_dates(body):
            if when - now > timedelta(days=2):
                out.append(Finding("T7", "future_date", "red", f"{when.date()} is in the future", path))
                break
    return out


# ── T8 latency ────────────────────────────────────────────────────────────


def check_latency(code: str, seconds: float, *, warm: bool, cfg: TruthConfig, timed_out: bool = False) -> list[Finding]:
    if timed_out:
        return [Finding("T8", "timeout", "red", f"no response within {seconds:.1f}s")]
    budget = {**cfg.latency_budget_s, **cfg.latency_overrides.get(code.upper(), {})}
    limit = float(budget["warm" if warm else "cold"])
    if seconds > limit:
        return [Finding("T8", "slow", "amber", f"{'warm' if warm else 'cold'} {seconds:.1f}s > {limit:.0f}s budget")]
    return []


# ── grading ───────────────────────────────────────────────────────────────

GREEN, AMBER, RED, NETWORK_FLAKE = "GREEN", "AMBER", "RED", "NETWORK_FLAKE"


def grade(
    findings: list[Finding], *, status: str, keyless_alternative_known: bool, network_flake: bool = False
) -> str:
    if network_flake:
        return NETWORK_FLAKE
    if any(f.severity == "red" for f in findings):
        return RED
    status = (status or "").lower()
    if status in {"calc_error", "input_error"}:
        return RED
    if status in {"provider_unavailable", "empty"}:
        return RED if keyless_alternative_known else AMBER
    if findings:
        return AMBER
    return GREEN
