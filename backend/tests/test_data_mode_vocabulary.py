"""Repo-wide data_mode vocabulary conformance (survey fast-follow).

Every ``data_mode`` literal emitted anywhere under ``showme/engine`` must
belong to ONE frozen sanctioned vocabulary. Before this test the values
drifted per-function (the R2 L-3 finding: GLCO emitted ``"reference"``
while the UI strip vocabulary knows ``delayed_reference``; OVDV once
shipped UPPERCASE modes). This test makes vocabulary drift a CI failure
instead of a review catch.

Part (a) is a deterministic static scan (no network, no imports of the
engines): both emission forms are scanned —

    data_mode = "value"          /  data_mode="value"
    "data_mode": "value"         (dict metadata literals)

Part (b) checks the sanitizer contract over the same vocabulary: only
``live*`` modes may prove liveness, and the sanitizer's failure-mode set
must stay a subset of the sanctioned vocabulary (both drift directions).

TO ADD A NEW VALUE: extend ``SANCTIONED_DATA_MODES`` deliberately in the
same commit as the new emitter (and mirror it into the UI strip
vocabulary in ui/src/shell/PaneChrome.tsx when it should tone-map).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme import server  # noqa: E402

ENGINE_DIR = _BACKEND_DIR / "showme" / "engine"

# The frozen sanctioned vocabulary — exactly the set of data_mode literals
# emitted under showme/engine at freeze time (2026-09-09, lane E).
SANCTIONED_DATA_MODES = frozenset({
    # live states
    "live",
    "live_official",
    "live_exchange",
    "live_yfinance",
    # R3 M-1: the fx suite emits metadata via ``{"data_mode": source_mode}``
    # (a variable), so the static literal scan cannot see these — they were
    # manually traced to their emitters (fx/_funcs.py) and frozen here:
    # FXFC/FRD/OVDV spot tier + WCRS cross-matrix tier.
    "manual_input",
    "live_yfinance_quote",
    "live_ecb_reference",
    "live_exchangerate_host",
    "reference_cross_rate_matrix",
    # reference / delayed states
    "delayed_reference",
    "reference",
    "cached_snapshot",
    # computed / model states
    "modeled",
    "user_input",
    "user_supplied",
    # honest failure / absence states
    "provider_unavailable",
    "not_configured",
    "explicit_unavailable",
    "unavailable",
    "no_fills",
    "no_live_source",
    "empty",
    "off",
})

_LIVE_CLAIM_MODES = frozenset(v for v in SANCTIONED_DATA_MODES if v.startswith("live"))

# Both literal emission forms, one value per match.
_DATA_MODE_PATTERN = re.compile(
    r"""data_mode\s*=\s*["']([a-z_]+)["']"""
    r"""|["']data_mode["']\s*:\s*["']([a-z_]+)["']"""
)


def _scan_engine_data_mode_literals() -> dict[str, list[str]]:
    """Return {value: ["file:line", ...]} for every data_mode literal."""
    found: dict[str, list[str]] = {}
    for path in sorted(ENGINE_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in _DATA_MODE_PATTERN.finditer(line):
                value = match.group(1) or match.group(2)
                found.setdefault(value, []).append(f"{path.relative_to(_BACKEND_DIR)}:{lineno}")
    return found


def test_engine_data_mode_literals_are_all_sanctioned() -> None:
    found = _scan_engine_data_mode_literals()
    offenders = {
        value: sites for value, sites in found.items() if value not in SANCTIONED_DATA_MODES
    }
    assert not offenders, (
        "data_mode literal(s) outside the sanctioned vocabulary — extend "
        f"SANCTIONED_DATA_MODES deliberately or use an existing value: {offenders}"
    )


# R3 M-1: values emitted DYNAMICALLY (``{"data_mode": source_mode}`` with a
# variable) — invisible to the literal scan, so they cannot participate in
# the bidirectional freeze. They are pinned by trace: each entry names the
# emitter family that produces it. A future edit that renames or drops one
# of these emitters must update this set in the same commit.
DYNAMICALLY_EMITTED_MODES = frozenset({
    "manual_input",             # FXFC/FRD user-supplied quotes
    "live_yfinance_quote",      # fx spot keyed yfinance tier
    "live_ecb_reference",       # fx spot keyed ECB tier
    "live_exchangerate_host",   # WCRS cross-matrix keyed tier
    "reference_cross_rate_matrix",  # WCRS labelled reference matrix
})


def test_sanctioned_vocabulary_matches_emitted_set_exactly() -> None:
    """Freeze guard, scoped to what a static scan can honestly see.

    Direction 1 (regression catcher): every literal emitted under
    showme/engine must be sanctioned — a new off-vocabulary literal fails
    CI. Direction 2 (prune catcher): the vocabulary is exactly the literal
    set PLUS the traced dynamic set — a literal removed from the engines
    must be pruned in the same commit.
    """
    found = _scan_engine_data_mode_literals()
    unsanctioned = set(found) - set(SANCTIONED_DATA_MODES)
    unemitted = set(SANCTIONED_DATA_MODES) - set(found) - DYNAMICALLY_EMITTED_MODES
    assert not unsanctioned and not unemitted, (
        "vocabulary drift: "
        f"emitted-but-unsanctioned={sorted(unsanctioned)} "
        f"sanctioned-but-unemitted={sorted(unemitted)}"
    )


@pytest.mark.parametrize("mode", sorted(SANCTIONED_DATA_MODES))
def test_sanitizer_accepts_every_sanctioned_mode(mode: str) -> None:
    """Sanitizer contract over the frozen vocabulary: a data_mode proves
    liveness IFF it is an explicit ``live*`` claim. Failure/absence modes
    can never voucher a LIVE pill."""
    proves_live = server._metadata_proves_live({"data_mode": mode})
    assert proves_live == (mode in _LIVE_CLAIM_MODES), (
        f"data_mode={mode!r} prove-live={proves_live} violates the contract"
    )


def test_sanitizer_failure_modes_stay_subset_of_vocabulary() -> None:
    """The sanitizer's failure-mode veto set must stay inside the frozen
    vocabulary, so a rename there cannot silently strand a value."""
    assert server._FAILURE_DATA_MODES <= SANCTIONED_DATA_MODES
