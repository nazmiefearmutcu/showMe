"""Bundle C / C3 regression: EQS returns a dict envelope on DSL parse failure.

Previously the DSL-error branch returned a raw pandas DataFrame as ``data``
which broke every UI consumer (they all expect ``{rows, status, ...}``).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.equity.eqs import EQSFunction  # noqa: E402


async def test_dsl_parse_error_returns_dict_envelope_not_dataframe() -> None:
    fn = EQSFunction()
    # Garbage that the recursive-descent parser cannot consume.
    result = await fn.execute(instrument=None, query="???? @@ broken", live_screen=False)
    data = result.data
    assert isinstance(data, dict), (
        f"Expected dict envelope, got {type(data).__name__}"
    )
    assert data["status"] == "dsl_parse_error"
    assert "error" in data
    assert data["rows"] == []
    # ``warnings`` should also be populated.
    assert any("DSL parse error" in w for w in result.warnings)


async def test_dsl_parse_error_preserves_query_and_scanned_count() -> None:
    fn = EQSFunction()
    result = await fn.execute(instrument=None, query="@@ totally broken", live_screen=False)
    assert result.data["query"] == "@@ totally broken"
    assert isinstance(result.data["scanned"], int)
    assert result.data["scanned"] > 0  # the stub universe was built first


async def test_valid_dsl_still_returns_filtered_rows() -> None:
    """Sanity: success path unchanged."""
    fn = EQSFunction()
    result = await fn.execute(
        instrument=None,
        query="marketCap > 1000000000",
        live_screen=False,
    )
    # Success path returns a DataFrame as ``data`` (legacy contract is fine here).
    import pandas as pd
    assert isinstance(result.data, pd.DataFrame)
    assert len(result.data) > 0
