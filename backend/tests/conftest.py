"""Suite-wide isolation: tests never read or write the user's real app home.

Before 2026-11-08 there was no conftest, so any test that touched the
portfolio, margin, order or tax-lot stores without setting ``SHOWME_HOME``
itself resolved ``%APPDATA%\\showMe`` (or ``~/Library/Application Support``)
and could read the user's real portfolio or write files into it — e.g. the
margin engine creating ``runtime/margin_config.json``.

``SHOWME_HOME`` is pointed at a throwaway directory before any test module
imports ``showme`` (paths are resolved at call time via
``showme.app_paths``). Tests that set their own ``SHOWME_HOME`` still win.
Bots never start in test-built apps.
"""
from __future__ import annotations

import os
import shutil
import tempfile

_TEST_HOME = tempfile.mkdtemp(prefix="showme-test-home-")
os.environ["SHOWME_HOME"] = _TEST_HOME
os.environ.setdefault("SHOWME_DISABLE_BOTS", "1")


def pytest_unconfigure(config):  # noqa: ARG001 - pytest hook signature
    shutil.rmtree(_TEST_HOME, ignore_errors=True)
