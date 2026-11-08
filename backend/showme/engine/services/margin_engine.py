"""Cross-account margin engine.

Tracks per-account haircuts, margin requirements, and buying power. Supports:
- **Reg-T** style: 50% initial, 25% maintenance for equities.
- **Portfolio margin**: stress-test based — uses worst case of  ±15% vs flat.
- **Crypto**: configurable initial/maintenance per exchange.
- **Futures**: SPAN-lite — fixed margin per contract.

Persistence: ``runtime/margin_config.json`` for account configs and overrides.
"""

from __future__ import annotations

import json
from typing import Any

from showme.app_paths import runtime_path
from showme.engine.portfolio.state import PortfolioState


def _config_path():
    return runtime_path("margin_config.json")


# ─── Default rules ───────────────────────────────────────────────────
DEFAULT_RULES: dict[str, dict[str, Any]] = {
    "reg_t": {
        "initial_long_pct": 0.50,
        "maintenance_long_pct": 0.25,
        "initial_short_pct": 1.50,
        "maintenance_short_pct": 0.30,
        "asset_classes": ["EQUITY", "ETF"],
    },
    "portfolio": {
        "stress_pct": 0.15,
        "min_pct": 0.10,
        "asset_classes": ["EQUITY", "ETF"],
    },
    "crypto_spot": {
        "initial_long_pct": 1.00,
        "maintenance_long_pct": 0.30,
        "initial_short_pct": 1.50,
        "maintenance_short_pct": 0.30,
        "asset_classes": ["CRYPTO"],
    },
    "crypto_futures": {
        "initial_long_pct": 0.10,    # 10x leverage default
        "maintenance_long_pct": 0.05,
        "initial_short_pct": 0.10,
        "maintenance_short_pct": 0.05,
        "asset_classes": ["CRYPTO", "DERIVATIVE"],
    },
    "futures": {
        "fixed_initial_per_contract": 12000.0,    # ES/NQ ballpark
        "fixed_maintenance_per_contract": 10000.0,
        "asset_classes": ["DERIVATIVE", "COMMODITY"],
    },
    "fx": {
        "initial_long_pct": 0.02,
        "maintenance_long_pct": 0.01,
        "initial_short_pct": 0.02,
        "maintenance_short_pct": 0.01,
        "asset_classes": ["FX"],
    },
    "bond": {
        "initial_long_pct": 0.15,
        "maintenance_long_pct": 0.07,
        "asset_classes": ["BOND"],
    },
}


# Asset class -> rule a position of that class is margined under. A position uses
# its own class rule whenever the account's rule does not cover that class, so one
# account can hold spot crypto and equities without either being priced at the
# other's rate (MGN#2), and a reg_t account's BTC is not margined at 50% (MGN#3).
_CLASS_RULE: dict[str, str] = {
    "CRYPTO": "crypto_spot",
    "EQUITY": "reg_t",
    "ETF": "reg_t",
    "FX": "fx",
    "BOND": "bond",
}


def _is_crypto_perpetual(symbol: str) -> bool:
    """True for a crypto perpetual/swap symbol (``BTC-PERP``, ``BTC-SWAP``, ccxt ``BTC/USDT:USDT``)."""
    s = str(symbol or "").upper()
    return s.endswith(("-PERP", "-SWAP", "PERP")) or ":" in s


def _book_class(position: dict[str, Any]) -> str:
    """Asset class used for account inference: a crypto perpetual is its own token.

    A perpetual is held as asset_class CRYPTO (MGN#2-RQ), so it is told apart from spot
    CRYPTO by its symbol suffix, not by its class label.
    """
    cls = str(position.get("asset_class") or "").upper()
    if cls == "CRYPTO" and _is_crypto_perpetual(str(position.get("symbol") or "")):
        return "CRYPTO_PERP"
    return cls


def infer_margin_type(positions: list[dict[str, Any]]) -> str:
    """Account-level margin type implied by the products an account holds.

    Only an account made purely of spot crypto is crypto_spot. A crypto account that
    also holds derivatives (CRYPTO and DERIVATIVE both present) is crypto_futures, and so
    is any book holding a crypto perpetual (CRYPTO_PERP). A DERIVATIVE-only book is
    futures: a DERIVATIVE is non-crypto futures/options, so it must not take the crypto
    10% rule. Each position is still priced under its own class rule in calc_account.
    """
    classes = {_book_class(p) for p in positions}
    if classes and classes <= {"CRYPTO"}:
        return "crypto_spot"
    if "CRYPTO_PERP" in classes and classes <= {"CRYPTO", "CRYPTO_PERP", "DERIVATIVE"}:
        return "crypto_futures"
    if classes and classes <= {"CRYPTO", "DERIVATIVE"} and {"CRYPTO", "DERIVATIVE"} <= classes:
        return "crypto_futures"
    if classes & {"FX"}:
        return "fx"
    if classes & {"COMMODITY", "DERIVATIVE"}:
        return "futures"
    return "reg_t"


def _position_rule(
    asset_class: str,
    margin_type: str,
    account_rule: dict[str, Any],
    *,
    explicit: bool = True,
    symbol: str = "",
) -> dict[str, Any]:
    """Rule for one position: the account rule, unless its class has its own rule.

    ``explicit`` is False when the account type was inferred from the book (MGN#2
    residual): an inferred crypto_futures account must not reprice spot CRYPTO lines.
    In such an inferred account a non-perpetual DERIVATIVE (ES, options) takes the
    futures rule; a crypto perpetual keeps the crypto_futures rate.
    """
    cls = str(asset_class or "").upper()
    if (cls == "DERIVATIVE" and margin_type == "crypto_futures" and not explicit
            and not _is_crypto_perpetual(symbol)):
        return dict(DEFAULT_RULES["futures"])
    # MGN#2-RQ: a crypto perpetual held as CRYPTO keeps the crypto_futures rate; only the
    # spot CRYPTO lines of the same book are priced at the crypto_spot rate.
    if cls == "CRYPTO" and _is_crypto_perpetual(symbol):
        return account_rule if margin_type == "crypto_futures" else dict(DEFAULT_RULES["crypto_futures"])
    mapped = _CLASS_RULE.get(cls)
    if mapped is None or mapped == margin_type:
        return account_rule
    # An account the user set to crypto_futures keeps its crypto rule (explicit choice).
    if cls == "CRYPTO" and margin_type == "crypto_futures" and explicit:
        return account_rule
    return dict(DEFAULT_RULES[mapped])


def _load_config() -> dict[str, Any]:
    if not _config_path().exists():
        return {}
    try:
        return json.loads(_config_path().read_text())
    except Exception:
        return {}


def _save_config(cfg: dict[str, Any]) -> None:
    _config_path().parent.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(cfg, indent=2))


def list_accounts() -> list[dict[str, Any]]:
    cfg = _load_config()
    return [
        {"account": a, **info}
        for a, info in (cfg.get("accounts") or {}).items()
    ]


def upsert_account(
    name: str,
    *,
    margin_type: str = "reg_t",
    cash: float = 0.0,
    currency: str = "USD",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = _load_config()
    accounts = cfg.setdefault("accounts", {})
    accounts[name] = {
        "margin_type": margin_type,
        "cash": float(cash),
        "currency": currency,
        "overrides": overrides or {},
    }
    _save_config(cfg)
    return accounts[name]


def delete_account(name: str) -> bool:
    cfg = _load_config()
    accounts = cfg.setdefault("accounts", {})
    if name in accounts:
        accounts.pop(name)
        _save_config(cfg)
        return True
    return False


def _rule_for(margin_type: str) -> dict[str, Any]:
    return DEFAULT_RULES.get(margin_type, DEFAULT_RULES["reg_t"])


def _position_margin(
    pos: dict[str, Any], rule: dict[str, Any]
) -> tuple[float, float]:
    """Return (initial, maintenance) for one position dict."""
    qty = float(pos.get("quantity", 0) or 0)
    px = float(pos.get("last", pos.get("avg_cost", 0)) or 0)
    notional = abs(qty * px)
    if "fixed_initial_per_contract" in rule:
        contracts = abs(qty)
        return (rule["fixed_initial_per_contract"] * contracts,
                rule["fixed_maintenance_per_contract"] * contracts)
    if qty >= 0:
        ip = rule.get("initial_long_pct", 0.5)
        mp = rule.get("maintenance_long_pct", 0.25)
    else:
        ip = rule.get("initial_short_pct", 1.5)
        mp = rule.get("maintenance_short_pct", 0.30)
    return (notional * ip, notional * mp)


def _portfolio_margin(positions: list[dict[str, Any]], rule: dict[str, Any]) -> tuple[float, float]:
    """Stress-based margin: max loss under ±stress_pct shock."""
    stress = float(rule.get("stress_pct", 0.15))
    minp = float(rule.get("min_pct", 0.10))
    pnl_up = 0.0
    pnl_dn = 0.0
    notional = 0.0
    for p in positions:
        qty = float(p.get("quantity", 0) or 0)
        px = float(p.get("last", p.get("avg_cost", 0)) or 0)
        nv = qty * px
        notional += abs(nv)
        pnl_up += nv * stress
        pnl_dn += -nv * stress
    worst = -min(pnl_up, pnl_dn)
    floor = notional * minp
    return max(worst, floor), max(worst * 0.6, floor * 0.6)


def calc_account(
    account_name: str,
    positions: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or _load_config()
    info = (cfg.get("accounts") or {}).get(account_name) or {}
    margin_type = info.get("margin_type", "reg_t")
    explicit = not info.get("inferred")
    rule = {**_rule_for(margin_type), **(info.get("overrides") or {})}
    # Rule that sets buying power: the rule of the largest position by notional.
    bp_rule = rule
    if margin_type == "portfolio":
        ip, mp = _portfolio_margin(positions, rule)
        per_pos = []
    else:
        ip = mp = 0.0
        per_pos = []
        biggest = -1.0
        for p in positions:
            p_rule = _position_rule(p.get("asset_class", ""), margin_type, rule,
                                    explicit=explicit, symbol=str(p.get("symbol") or ""))
            i, m = _position_margin(p, p_rule)
            ip += i
            mp += m
            per_pos.append({**p, "initial_margin": i, "maintenance_margin": m})
            notional = abs(float(p.get("quantity", 0) or 0)
                           * float(p.get("last", p.get("avg_cost", 0)) or 0))
            if notional > biggest:
                biggest, bp_rule = notional, p_rule
    cash = float(info.get("cash", 0) or 0)
    mv = sum(float(p.get("quantity", 0) or 0) * float(p.get("last", p.get("avg_cost", 0)) or 0)
             for p in positions)
    equity = cash + mv
    excess = equity - ip
    cushion = (equity - mp) / equity if equity else 0.0
    buying_power = max(equity - ip, 0) / max(bp_rule.get("initial_long_pct", 0.5), 0.05) \
        if margin_type != "portfolio" else max(equity - ip, 0) * 4
    return {
        "account": account_name,
        "margin_type": margin_type,
        "currency": info.get("currency", "USD"),
        "cash": cash,
        "market_value": mv,
        "equity": equity,
        "initial_margin": ip,
        "maintenance_margin": mp,
        "excess_initial": excess,
        "excess_maintenance": equity - mp,
        "maintenance_cushion_pct": cushion * 100,
        "buying_power": buying_power,
        "positions": per_pos,
    }


def calc_all_accounts(
    prices: dict[str, float] | None = None,
    *,
    include_legacy: bool = False,
) -> dict[str, Any]:
    portfolio = PortfolioState()
    if include_legacy:
        portfolio.import_legacy_crypto()
    cfg = _load_config()
    accts: dict[str, list[dict[str, Any]]] = {}
    for p in portfolio.positions:
        sym = p.instrument.symbol
        px = (prices or {}).get(sym) or p.avg_cost
        accts.setdefault(p.account or "main", []).append({
            "symbol": sym, "asset_class": p.instrument.asset_class.value,
            "quantity": p.quantity, "avg_cost": p.avg_cost, "last": px,
            "currency": p.currency,
        })
    # Auto-create accounts if missing. An inferred type is flagged and re-derived from
    # the current book, so a book that loses its derivative is not stuck as crypto_futures.
    cfg_accts = cfg.setdefault("accounts", {})
    for name, positions in accts.items():
        inferred = infer_margin_type(positions)
        entry = cfg_accts.get(name)
        if entry is None:
            cfg_accts[name] = {
                "margin_type": inferred, "cash": 0.0,
                "currency": "USD", "overrides": {}, "inferred": True,
            }
        elif entry.get("inferred"):
            entry["margin_type"] = inferred
    _save_config(cfg)
    out = []
    total = {
        "equity": 0.0, "initial_margin": 0.0, "maintenance_margin": 0.0,
        "buying_power": 0.0, "excess_initial": 0.0,
    }
    for name, positions in accts.items():
        a = calc_account(name, positions, cfg=cfg)
        out.append(a)
        for k in total:
            total[k] += a.get(k, 0)
    total["maintenance_cushion_pct"] = (
        (total["equity"] - total["maintenance_margin"]) / total["equity"] * 100
        if total["equity"] else 0
    )
    return {"accounts": out, "total": total}
