"""The boot prewarm must fill the SWR entry the Welcome dashboard actually reads.

Welcome's NewsflowPanel calls TOP with ``{ hours: 48, limit: 24, _epoch }``. If the
prewarm sends different params it warms a key nobody reads and the landing page
always takes the cold path (news review I3).
"""

from __future__ import annotations

import re
from pathlib import Path

from showme.server import HOME_PREWARM_PARAMS, home_swr_key

WELCOME = Path(__file__).resolve().parents[2] / "ui" / "src" / "panes" / "Welcome.tsx"


def _welcome_params(code: str) -> dict[str, str]:
    """Literal params object of the Welcome ``useFunction`` call for ``code``."""
    source = WELCOME.read_text(encoding="utf-8")
    match = re.search(r'code:\s*"' + code + r'",\s*params:\s*\{([^}]*)\}', source)
    assert match, f"Welcome.tsx no longer calls {code} with a literal params object"
    params: dict[str, str] = {}
    for part in match.group(1).split(","):
        if ":" not in part:
            continue
        key, value = (piece.strip() for piece in part.split(":", 1))
        params[key] = value
    return params


def test_top_prewarm_params_equal_the_welcome_newsflow_params() -> None:
    welcome = {k: v for k, v in _welcome_params("TOP").items() if not k.startswith("_")}
    prewarm = {k: v for k, v in HOME_PREWARM_PARAMS["TOP"].items() if not k.startswith("_")}
    assert welcome == {"hours": "48", "limit": "24"}
    assert prewarm == welcome


def test_top_prewarm_and_welcome_land_on_the_same_swr_key() -> None:
    # JSON body from the UI (numbers, a live epoch) vs the GET-style prewarm (strings).
    from_ui = home_swr_key("TOP", {"hours": 48, "limit": 24, "_epoch": 1731050000000})
    from_prewarm = home_swr_key("TOP", dict(HOME_PREWARM_PARAMS["TOP"]))
    assert from_ui == from_prewarm


def test_most_and_brief_prewarm_params_match_welcome() -> None:
    most = _welcome_params("MOST")
    assert {k: v.lower() for k, v in most.items()} == {
        k: v for k, v in HOME_PREWARM_PARAMS["MOST"].items()
    }
    brief = _welcome_params("BRIEF")
    assert brief == {"limit": "BRIEF_DISPLAY_LIMIT"}
    limit = re.search(
        r"export const BRIEF_DISPLAY_LIMIT = (\d+);", WELCOME.read_text(encoding="utf-8")
    )
    assert limit and HOME_PREWARM_PARAMS["BRIEF"] == {"limit": limit.group(1)}
