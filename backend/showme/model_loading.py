"""Serialize model construction that temporarily patches global torch state.

Transformers' init_empty_weights/no_init_weights replace nn.Module and
torch.nn.init functions process-wide. Per-model singleton locks cannot stop
one model's loader from moving another model's parameters back to meta.
Inference remains independent; only construction needs this shared lock.
"""
from __future__ import annotations

from functools import wraps
from threading import RLock
from typing import Callable, ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")
_MODEL_LOAD_LOCK = RLock()


def serialized_model_load(loader: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(loader)
    def guarded(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        with _MODEL_LOAD_LOCK:
            return loader(*args, **kwargs)

    return guarded
