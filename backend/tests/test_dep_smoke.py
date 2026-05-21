"""Sub-system A dep smoke: ccxt + keyring import without error.

Per spec §10 step 1: we want CI to fail fast if either dep regresses or
PyInstaller drops them at packaging time.
"""
from __future__ import annotations


def test_ccxt_imports() -> None:
    import ccxt  # noqa: F401
    import ccxt.async_support  # noqa: F401
    assert hasattr(ccxt, "exchanges")
    # We don't pin a specific count; just assert the registry is populated.
    assert len(ccxt.exchanges) > 50


def test_keyring_imports() -> None:
    import keyring  # noqa: F401
    # macOS default backend should exist; in CI it may fall back to the
    # null backend — both are acceptable for the import smoke.
    backend = keyring.get_keyring()
    assert backend is not None
