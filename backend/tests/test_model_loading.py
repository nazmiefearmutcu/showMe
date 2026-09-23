"""Cross-model startup must not overlap transformers' global init contexts."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import sys

import pytest

from showme.finbert_analyzer import FinBertAnalyzer
from showme.model_loading import serialized_model_load
from showme.whisper_analyzer import WhisperAnalyzer


def test_finbert_waits_for_whisper_model_construction(monkeypatch):
    whisper_entered = Event()
    release_whisper = Event()
    finbert_attempted = Event()
    finbert_entered = Event()

    def pipeline(task, **kwargs):
        if task == "automatic-speech-recognition":
            whisper_entered.set()
            assert release_whisper.wait(5)
        else:
            finbert_entered.set()
        return object()

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(pipeline=pipeline))

    def load_finbert():
        finbert_attempted.set()
        return FinBertAnalyzer()

    with ThreadPoolExecutor(2) as pool:
        whisper = pool.submit(WhisperAnalyzer)
        try:
            assert whisper_entered.wait(5)
            finbert = pool.submit(load_finbert)
            assert finbert_attempted.wait(5)
            assert not finbert_entered.wait(0.2)
        finally:
            release_whisper.set()
        assert whisper.result(timeout=5)._pipe is not None
        assert finbert.result(timeout=5)._pipe is not None
        assert finbert_entered.is_set()


def test_failed_model_load_releases_lock_for_other_threads():
    @serialized_model_load
    def broken():
        raise ValueError("bad checkpoint")

    @serialized_model_load
    def healthy():
        return "loaded"

    with pytest.raises(ValueError, match="bad checkpoint"):
        broken()
    with ThreadPoolExecutor(1) as pool:
        assert pool.submit(healthy).result(timeout=5) == "loaded"


def test_nested_model_load_does_not_deadlock():
    @serialized_model_load
    def inner():
        return "loaded"

    assert serialized_model_load(inner)() == "loaded"
