"""ALRT contract: list emits the ``rows`` key the seed's output contract requires.

alrt_seed.py declares ``output_contract.must_have=["rows"]`` and a table whose
columns read each rule's fields. ``list`` returned the rules only under
``alerts``, so a rows-based table had nothing to show. ``rows`` now carries the
same rules, with the table's column keys present on each row.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
for p in (str(BACKEND), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from showme.engine.functions.misc.alrt import ALRTFunction  # noqa: E402
from showme.manifest.seeds.alrt_seed import alrt  # noqa: E402


@pytest.fixture
def alrt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield tmp_path


def test_seed_requires_rows_in_the_payload() -> None:
    assert "rows" in alrt.output_contract.must_have, alrt.output_contract.must_have


@pytest.mark.asyncio
async def test_list_emits_rows_matching_alerts(alrt_home: Path) -> None:
    fn = ALRTFunction()
    await fn.execute(action="add", condition="AAPL.price > 200", note="breakout")
    listed = (await fn.execute(action="list")).data

    assert "rows" in listed, sorted(listed)
    assert listed["rows"] == listed["alerts"], listed
    assert listed["count"] == len(listed["rows"]) == 1


@pytest.mark.asyncio
async def test_rows_carry_every_table_column(alrt_home: Path) -> None:
    fn = ALRTFunction()
    await fn.execute(action="add", condition="AAPL.price > 200")
    row = (await fn.execute(action="list")).data["rows"][0]

    column_keys = {c.key for c in alrt.table_schema.columns if c.key}
    missing = column_keys - set(row)
    assert not missing, f"table columns with no row value: {sorted(missing)}"
