"""ALRT#4 follow-up: every unreadable alerts.json is refused the same way.

``_load_alerts`` caught only JSON and shape errors. A store that is not valid
text (UnicodeDecodeError) or cannot be read at all (OSError) escaped as an
exception instead of the input_error refusal that protects the file from being
overwritten. Nothing is written in those cases; the fix is the honest response.
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

from showme.engine.functions.misc.alrt import ALRTFunction, _store  # noqa: E402

# Invalid UTF-8 and undefined cp1252 bytes, so decoding fails under either codec.
_NOT_TEXT = b"\xff\xfe\x81\x8d[{\"id\": \"old1\""


@pytest.fixture
def alrt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield tmp_path


@pytest.mark.asyncio
async def test_add_refuses_a_store_that_is_not_text(alrt_home: Path) -> None:
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_bytes(_NOT_TEXT)

    res = await ALRTFunction().execute(action="add", condition="MSFT.price > 400")

    assert res.data["status"] == "input_error", res.data
    assert store.read_bytes() == _NOT_TEXT, "unreadable store was overwritten"
    assert any("unreadable" in w for w in res.warnings), res.warnings


@pytest.mark.asyncio
async def test_list_reports_a_store_that_is_not_text(alrt_home: Path) -> None:
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_bytes(_NOT_TEXT)

    res = await ALRTFunction().execute(action="list")

    assert res.data["count"] == 0, res.data
    assert any("unreadable" in w for w in res.warnings), res.warnings


@pytest.mark.asyncio
async def test_add_refuses_a_store_that_cannot_be_read(alrt_home: Path) -> None:
    """A directory where alerts.json should be is an OSError on read."""
    store = _store()
    store.mkdir(parents=True, exist_ok=True)

    res = await ALRTFunction().execute(action="add", condition="MSFT.price > 400")

    assert res.data["status"] == "input_error", res.data
    assert store.is_dir(), "the unreadable path was touched"
    assert any("unreadable" in w for w in res.warnings), res.warnings
