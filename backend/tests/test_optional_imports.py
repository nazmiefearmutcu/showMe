"""Optional third-party packages must not break module import.

``python-binance`` is an optional extra (it is only needed for a Binance
connection). Before 2026-11-07 ``engine/api/binance_client.py`` imported it
unconditionally, so on a clean install ``engine.data.market_data``,
``engine.trading.execution_engine`` and ``engine.services.bot_service`` —
and every test that touches them — failed at import time. The contract now:
the modules import without the package, and only an actual Binance
connection attempt fails, with an explicit, typed reason.
"""
from __future__ import annotations

import importlib
import sys

import pytest

_BLOCKED = ("binance", "binance.client", "binance.exceptions")
_DEPENDENTS = (
    "showme.engine.api.binance_client",
    "showme.engine.data.market_data",
    "showme.engine.trading.execution_engine",
    "showme.engine.services.bot_service",
)


def _set_parent_attr(name: str, module) -> None:
    parent_name, _, child = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is None:
        return
    if module is None:
        if hasattr(parent, child):
            delattr(parent, child)
    else:
        setattr(parent, child, module)


@pytest.fixture
def no_binance(monkeypatch):
    """Simulate an environment where python-binance is not installed.

    Every ``showme.*`` module (re)imported under the blocked environment is
    dropped afterwards and the originals are put back — including the
    parent-package attributes — so no later test sees the stub variant.
    """
    showme_before = {k: v for k, v in sys.modules.items() if k.startswith("showme")}
    for name in _BLOCKED:
        # A ``None`` entry in sys.modules makes ``import name`` raise ImportError.
        monkeypatch.setitem(sys.modules, name, None)
    for name in _DEPENDENTS:
        sys.modules.pop(name, None)  # force a fresh import under the blocked env
    yield
    for name in [k for k in sys.modules if k.startswith("showme")]:
        if sys.modules[name] is not showme_before.get(name):
            del sys.modules[name]
            _set_parent_attr(name, None)
    for name, module in showme_before.items():
        sys.modules[name] = module
        _set_parent_attr(name, module)


def test_fixture_blocks_python_binance(no_binance):
    """Sanity pin for the fixture itself: blocked imports really are blocked."""
    with pytest.raises(ImportError):
        importlib.import_module("binance.client")


@pytest.mark.parametrize("module_name", _DEPENDENTS)
def test_module_imports_without_python_binance(no_binance, module_name):
    module = importlib.import_module(module_name)
    assert module is not None


def test_binance_client_reports_missing_package_on_initialize(no_binance):
    binance_client = importlib.import_module("showme.engine.api.binance_client")
    assert binance_client.BINANCE_AVAILABLE is False

    client = binance_client.BinanceClient({"mode": "paper"})  # construction stays cheap
    with pytest.raises(binance_client.BinanceUnavailableError, match="python-binance"):
        client.initialize()


def test_fallback_exception_types_are_catchable(no_binance):
    binance_client = importlib.import_module("showme.engine.api.binance_client")
    for exc_type in (binance_client.BinanceAPIException, binance_client.BinanceRequestException):
        assert issubclass(exc_type, Exception)
        with pytest.raises(exc_type):
            raise exc_type("boom")
