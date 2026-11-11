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

import pytest

_TEST_HOME = tempfile.mkdtemp(prefix="showme-test-home-")
os.environ["SHOWME_HOME"] = _TEST_HOME
os.environ.setdefault("SHOWME_DISABLE_BOTS", "1")
# The in-memory credential backend is plaintext and needs this explicit opt-in
# (SEC-6). Tests only; test_credential_plaintext_guard.py clears it itself.
os.environ.setdefault("SHOWME_ALLOW_PLAINTEXT_VAULT", "1")


def pytest_unconfigure(config):  # noqa: ARG001 - pytest hook signature
    shutil.rmtree(_TEST_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clear_model_load_failure_latches():
    """A failed FinBERT/Whisper load latches for the process lifetime (by design,
    so production does not retry a 300 MB load per request). In the test process
    one test that makes the load fail (network cut, patched transformers) must
    not decide every later model test: clear only the failure latch, never a
    loaded instance, before each test."""
    import sys

    for mod_name, cls_name in (("showme.finbert_analyzer", "FinBertAnalyzer"),
                               ("showme.whisper_analyzer", "WhisperAnalyzer")):
        mod = sys.modules.get(mod_name)
        cls = getattr(mod, cls_name, None) if mod else None
        if cls is not None and getattr(cls, "_load_failed", False):
            cls._load_failed = False
            if hasattr(cls, "_load_error"):
                cls._load_error = None
    yield
