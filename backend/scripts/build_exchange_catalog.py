#!/usr/bin/env python3
"""Regenerate the ccxt section of exchanges.yml from ccxt's registry.

Output format is deliberately whitespace-stable so the CI diff check
(tests/test_catalog_regen.py) is meaningful. Hand-curated traditional
brokers live below the marker line and are preserved when --crypto-only
is passed.

Usage:
    python scripts/build_exchange_catalog.py \
        --output showme/brokers/catalog/exchanges.yml [--crypto-only]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import ccxt
import yaml


MARKER = "# --- TRADITIONAL BROKERS (hand-curated) ---"
CCXT_HEADER = (
    "# Auto-generated from ccxt.exchanges by scripts/build_exchange_catalog.py.\n"
    "# Do NOT hand-edit this section — re-run the generator after a ccxt bump.\n"
    "# The traditional-broker section below the marker IS hand-curated.\n"
)

REGION_HINTS = {
    "binance": ["global"], "binanceus": ["us"], "kraken": ["global"],
    "coinbase": ["us", "global"], "coinbaseadvanced": ["us"],
    "bybit": ["global"], "okx": ["global"], "kucoin": ["global"],
    "bitfinex": ["global"], "bitstamp": ["us", "eu"], "gemini": ["us"],
    "huobi": ["global"], "gateio": ["global"], "bitget": ["global"],
    "mexc": ["global"], "bingx": ["global"], "deribit": ["global"],
    "bitmex": ["global"], "phemex": ["global"], "poloniex": ["us"],
}


def _entry(ex_id: str) -> dict:
    try:
        cls = getattr(ccxt, ex_id)
    except AttributeError:
        return {}
    inst = cls({"enableRateLimit": True})
    requires = sorted(k for k, v in inst.requiredCredentials.items() if v)
    optional: list[str] = []
    asset_classes = []
    if inst.has.get("spot") or inst.has.get("fetchBalance"):
        asset_classes.append("spot")
    if inst.has.get("future") or inst.has.get("swap"):
        asset_classes.append("futures")
    if inst.has.get("option"):
        asset_classes.append("options")
    if inst.has.get("margin"):
        asset_classes.append("margin")
    if not asset_classes:
        asset_classes = ["spot"]
    capabilities = {
        "fetch_balance": bool(inst.has.get("fetchBalance")),
        "fetch_positions": bool(inst.has.get("fetchPositions")),
        "fetch_open_orders": bool(inst.has.get("fetchOpenOrders")),
        "create_order": bool(inst.has.get("createOrder")),
        "cancel_order": bool(inst.has.get("cancelOrder")),
    }
    return {
        "id": ex_id,
        "display_name": inst.name or ex_id.capitalize(),
        "aliases": [],
        "asset_classes": asset_classes,
        "regions": REGION_HINTS.get(ex_id, ["global"]),
        "adapter": "ccxt",
        "ccxt_id": ex_id,
        "requires": requires,
        "optional": optional,
        "capabilities": capabilities,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--crypto-only", action="store_true",
                   help="Emit only the ccxt-generated section (no traditional brokers).")
    args = p.parse_args()
    entries = [e for e in (_entry(x) for x in sorted(ccxt.exchanges)) if e]
    body = yaml.safe_dump(entries, sort_keys=False, default_flow_style=False,
                         allow_unicode=True)
    out = Path(args.output)
    if args.crypto_only:
        out.write_text(CCXT_HEADER + body)
        return
    existing = out.read_text() if out.exists() else ""
    trad = ""
    if MARKER in existing:
        trad = MARKER + existing.split(MARKER, 1)[1]
    else:
        trad = (
            MARKER + "\n"
            "# Hand-curate adapters below. Format mirrors the ccxt entries\n"
            "# but `adapter:` is the registered factory name (e.g. 'alpaca').\n"
            "\n"
            "- id: alpaca-live\n"
            "  display_name: Alpaca (live)\n"
            "  aliases: [alpaca]\n"
            "  asset_classes: [equity, crypto, options]\n"
            "  regions: [us]\n"
            "  adapter: alpaca\n"
            "  requires: [api_key, api_secret]\n"
            "  optional: []\n"
            "  capabilities:\n"
            "    fetch_balance: true\n"
            "    fetch_positions: true\n"
            "    fetch_open_orders: true\n"
            "    create_order: true\n"
            "    cancel_order: true\n"
        )
    out.write_text(CCXT_HEADER + body + "\n" + trad)


if __name__ == "__main__":
    main()
