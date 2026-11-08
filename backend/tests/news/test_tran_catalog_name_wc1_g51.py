"""Regression test for TRAN#1-RQ: the catalog name still called the 8-K earnings
press release an earnings call transcript.

The name must describe both sources the function can return, and the backend
class, the manifest and the UI static catalog must agree on it.
"""

from __future__ import annotations

import re
from pathlib import Path

from showme.engine.functions.news.tran import TRANFunction
from showme.manifest.seeds.tran_seed import tran as tran_manifest

_REPO = Path(__file__).resolve().parents[3]
_STATIC_INDEX = _REPO / "ui" / "src" / "functions" / "static-index.ts"


def _static_index_tran_name() -> str:
    text = _STATIC_INDEX.read_text(encoding="utf-8")
    m = re.search(r'"code":\s*"TRAN",\s*"name":\s*"([^"]+)"', text)
    assert m, "TRAN entry missing from static-index.ts"
    return m.group(1)


def test_tran_name_names_the_release_and_not_only_transcripts() -> None:
    assert "Release" in TRANFunction.name
    assert "Call Transcripts" not in TRANFunction.name


def test_tran_backend_manifest_and_static_catalog_share_the_name() -> None:
    assert TRANFunction.name == tran_manifest.name
    assert _static_index_tran_name() == TRANFunction.name
