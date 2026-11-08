"""ALRT#2 follow-up: the seed must not advertise direction options the handler refuses.

``cross_up`` / ``cross_down`` need a stateful crossing evaluator that this build
does not have, so ``add`` always returns ``input_error`` for them. Offering them
in the seed means the control always fails, so the seed may only list the
directions the handler actually stores.
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


def _direction_options() -> list[str]:
    spec = next(i for i in alrt.inputs if i.name == "direction")
    return list(spec.options or [])


def test_seed_offers_no_cross_direction() -> None:
    options = _direction_options()
    assert options, "direction must declare options"
    cross = [o for o in options if o.startswith("cross")]
    assert not cross, f"seed advertises directions the handler refuses: {cross}"


@pytest.mark.asyncio
async def test_every_seed_direction_option_is_accepted(alrt_home: Path) -> None:
    for option in _direction_options():
        res = await ALRTFunction().execute(
            action="add", symbol="AAPL", field="price", direction=option, threshold=200
        )
        assert res.data.get("status") != "input_error", (option, res.data)
        assert res.data.get("armed") is False, (option, res.data)
