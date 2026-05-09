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
from pathlib import Path
from typing import Any

from showme.engine.portfolio.state import PortfolioState

CONFIG_PATH = Path("runtime/margin_config.json")


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


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def _save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


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
    rule = {**_rule_for(margin_type), **(info.get("overrides") or {})}
    if margin_type == "portfolio":
        ip, mp = _portfolio_margin(positions, rule)
        per_pos = []
    else:
        ip = mp = 0.0
        per_pos = []
        for p in positions:
            i, m = _position_margin(p, rule)
            ip += i
            mp += m
            per_pos.append({**p, "initial_margin": i, "maintenance_margin": m})
    cash = float(info.get("cash", 0) or 0)
    mv = sum(float(p.get("quantity", 0) or 0) * float(p.get("last", p.get("avg_cost", 0)) or 0)
             for p in positions)
    equity = cash + mv
    excess = equity - ip
    cushion = (equity - mp) / equity if equity else 0.0
    buying_power = max(equity - ip, 0) / max(rule.get("initial_long_pct", 0.5), 0.05) \
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
    # Auto-create accounts if missing.
    cfg_accts = cfg.setdefault("accounts", {})
    for name in accts:
        cfg_accts.setdefault(name, {
            "margin_type": "reg_t", "cash": 0.0, "currency": "USD",
            "overrides": {},
        })
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
