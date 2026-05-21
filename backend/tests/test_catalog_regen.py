"""CI check: exchanges.yml in repo matches what build_exchange_catalog
emits today. Stops hand-edits of ccxt-section entries from drifting.

The hand-curated traditional-broker section is bracketed by
``# --- TRADITIONAL BROKERS (hand-curated) ---`` markers and excluded
from the comparison.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _crypto_section(text: str) -> str:
    marker = "# --- TRADITIONAL BROKERS (hand-curated) ---"
    return text.split(marker, 1)[0]


def test_catalog_crypto_section_matches_generator(tmp_path: Path) -> None:
    out = tmp_path / "exchanges.yml"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_exchange_catalog.py"),
         "--output", str(out), "--crypto-only"],
        check=True, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    in_repo = (REPO / "showme" / "brokers" / "catalog" / "exchanges.yml").read_text()
    regenerated = out.read_text()
    assert _crypto_section(in_repo).strip() == regenerated.strip(), (
        "Crypto section of exchanges.yml drifted from generator output. "
        "Run scripts/build_exchange_catalog.py --output showme/brokers/catalog/exchanges.yml"
    )
