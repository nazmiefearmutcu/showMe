"""BQUANT seed exposes only inputs the pane can actually set (BQUANT#2).

The BQUANT pane sends ``params: {}``, so a seed input such as ``examples_dir``
could never be changed from the UI: the field was dead. The seed now declares
no ``examples_dir`` input and the handler scans its fixed examples folder
(``backend/examples``) when a caller passes nothing.
"""

from __future__ import annotations

from showme.engine.functions.api import bquant as bquant_mod
from showme.manifest import REGISTRY, load_seeds


def _bquant_entry():
    load_seeds()
    return REGISTRY.get("BQUANT")


def test_seed_does_not_declare_a_dead_examples_dir_input() -> None:
    entry = _bquant_entry()
    names = {spec.name for spec in entry.inputs}
    assert "examples_dir" not in names
    assert "examples_dir" not in (entry.defaults or {})


def test_default_examples_root_is_the_backend_examples_folder() -> None:
    root = bquant_mod._examples_dir(None)
    assert root == bquant_mod._backend_root() / "examples"
