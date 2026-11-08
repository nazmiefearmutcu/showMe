"""REGM#2 — the REGM seed must not present controls the handler cannot honour.

* ``regime_taxonomy`` is read by no code, so it must not be a required input.
* ``window`` is read by action=history as an integer bar count. The seed offered
  month labels ("1m".."12m") with a "3m" default, which history mode rejects with
  input_error. It must be an integer control with an integer default.
* REGM never returns modeled data, so MODELED must not be an acceptable mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.manifest.enums import ControlKind, DataMode  # noqa: E402
from showme.manifest.seeds.regm_seed import regm  # noqa: E402


def _input(name: str):
    return next(i for i in regm.inputs if i.name == name)


def test_unread_taxonomy_input_is_not_required() -> None:
    spec = _input("regime_taxonomy")
    assert spec.required is False, "an input no code reads must not be required"


def test_window_is_an_integer_bar_count_control() -> None:
    spec = _input("window")
    assert spec.control == ControlKind.NUMBER, spec.control
    assert not spec.options, spec.options
    assert "not applied" in spec.description.lower(), spec.description


def test_window_default_is_an_integer_bar_count() -> None:
    value = regm.defaults.get("window")
    assert isinstance(value, int) and value > 0, value


def test_modeled_is_not_an_acceptable_regm_mode() -> None:
    assert DataMode.MODELED not in regm.provider_chain.acceptable_modes, (
        regm.provider_chain.acceptable_modes
    )
