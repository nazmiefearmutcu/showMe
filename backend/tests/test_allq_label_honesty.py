"""ALLQ labels must not present modeled quotes as a TRACE-derived view (ALLQ#6).

The methodology says rows are MODELED from one reference anchor and one spread
input, never observed dealer or TRACE quotes. The handler name and the seed
docstring still said "TRACE proxy", which contradicts that contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from showme.engine.functions.bond._stubs import ALLQFunction

_REPO = Path(__file__).resolve().parents[2]
_SEED = _REPO / "backend" / "showme" / "manifest" / "seeds" / "allq_seed.py"
_STATIC = _REPO / "ui" / "src" / "functions" / "static-index.ts"


def test_allq_handler_name_does_not_claim_trace_data() -> None:
    assert "TRACE" not in ALLQFunction.name.upper(), ALLQFunction.name
    assert "modeled" in ALLQFunction.name.lower() or "indicative" in ALLQFunction.name.lower()


def test_allq_seed_docstring_does_not_call_it_trace_proxy() -> None:
    first_line = _SEED.read_text(encoding="utf-8").splitlines()[0]
    assert "TRACE-proxy" not in first_line, first_line
    assert "TRACE proxy" not in first_line, first_line


def test_allq_static_catalog_name_matches_handler() -> None:
    text = _STATIC.read_text(encoding="utf-8")
    match = re.search(r'"code": "ALLQ",\s*"name": "([^"]+)"', text)
    assert match, "ALLQ entry missing from static-index.ts"
    assert match.group(1) == ALLQFunction.name


_PANE = _REPO / "ui" / "src" / "functions" / "ALLQ.tsx"


def test_allq_pane_does_not_claim_trace_proxy() -> None:
    # ALLQ#6-RQ: the pane header comment and subtitle must not call modeled rows a TRACE proxy.
    text = _PANE.read_text(encoding="utf-8")
    assert "TRACE proxy" not in text, "ALLQ.tsx still labels modeled quotes as a TRACE proxy"
    assert "indicative, modeled" in text or "modeled" in text.lower()
