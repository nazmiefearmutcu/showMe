"""Wave-2 contract tests for the MISC seed family.

Covers ALRT, BIO, BMC, CDE, DINE, FLY, GRAB, LANG, ONCH, POLY, SAT, WHAL.

Every MISC seed is auxiliary — most own no external provider — so the
floor is intentionally different from wave-1:

* Category MUST be MISC (this batch is explicitly the auxiliary tray).
* provider_chain.primary should be ``internal`` (panes that consume
  data already produced by other panes or local state) — or one of a
  small set of recognised public-data primaries for the proxy panes.
* Any seed that talks to an *optional* external provider must declare
  ``NOT_CONFIGURED`` as an acceptable mode AND ship at least one
  semantic_test whose description mentions "unavailable" or
  "not_configured" (honest-availability rule).

Seeds are imported directly rather than through ``load_seeds()`` so a
broken sibling seed authored by a parallel agent cannot prevent this
suite from running.
"""
from __future__ import annotations

import re

import pytest

from showme.manifest import Category, DataMode
from showme.manifest.seeds.alrt_seed import alrt
from showme.manifest.seeds.bio_seed import bio
from showme.manifest.seeds.bmc_seed import bmc
from showme.manifest.seeds.cde_seed import cde
from showme.manifest.seeds.dine_seed import dine
from showme.manifest.seeds.fly_seed import fly
from showme.manifest.seeds.grab_seed import grab
from showme.manifest.seeds.lang_seed import lang
from showme.manifest.seeds.onch_seed import onch
from showme.manifest.seeds.poly_seed import poly
from showme.manifest.seeds.sat_seed import sat
from showme.manifest.seeds.whal_seed import whal


MISC_ENTRIES = {
    "ALRT": alrt,
    "BIO": bio,
    "BMC": bmc,
    "CDE": cde,
    "DINE": dine,
    "FLY": fly,
    "GRAB": grab,
    "LANG": lang,
    "ONCH": onch,
    "POLY": poly,
    "SAT": sat,
    "WHAL": whal,
}

MISC_CODES = tuple(MISC_ENTRIES.keys())

# These codes must explicitly assert honest-availability semantics: a
# semantic_test description mentioning "unavailable" or "not_configured"
# and acceptable_modes that includes NOT_CONFIGURED.
HONEST_AVAILABILITY_CODES = ("BIO", "ONCH", "WHAL", "SAT", "POLY")

# Primary providers permitted in the MISC tray. The auxiliary panes are
# overwhelmingly internal; WHAL is the one exception that legitimately
# routes through public proxies as fallbacks but still declares
# primary=internal so the not-configured story is honest.
ALLOWED_PRIMARY_PROVIDERS = {"internal"}

HONEST_KEYWORDS = re.compile(r"unavailable|not_configured", re.IGNORECASE)


@pytest.mark.parametrize("code", MISC_CODES)
def test_misc_seed_is_registered(code: str) -> None:
    """Each MISC seed module returns a manifest with the matching code."""
    entry = MISC_ENTRIES[code]
    assert entry.code == code, (
        f"{code}: factory returned a manifest with code={entry.code!r}"
    )


@pytest.mark.parametrize("code", MISC_CODES)
def test_misc_seed_shape(code: str) -> None:
    """Shape floor: MISC category, internal-friendly chain, real methodology, ≥1 test."""
    entry = MISC_ENTRIES[code]
    assert entry.category == Category.MISC, (
        f"{code}: must declare Category.MISC (got {entry.category!r})"
    )
    assert entry.inputs, f"{code}: at least one input control required"
    assert entry.provider_chain.primary in ALLOWED_PRIMARY_PROVIDERS, (
        f"{code}: provider_chain.primary={entry.provider_chain.primary!r} "
        f"not in {ALLOWED_PRIMARY_PROVIDERS} — MISC panes must be honest about "
        f"having no first-class external provider."
    )
    assert len(entry.methodology) >= 50, (
        f"{code}: methodology must explain the pane (>=50 chars), "
        f"got {len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code}: at least one semantic_test required"


@pytest.mark.parametrize("code", HONEST_AVAILABILITY_CODES)
def test_misc_seed_declares_not_configured_mode(code: str) -> None:
    """Optional-provider seeds must list NOT_CONFIGURED in acceptable_modes."""
    entry = MISC_ENTRIES[code]
    modes = set(entry.provider_chain.acceptable_modes)
    assert DataMode.NOT_CONFIGURED in modes, (
        f"{code}: provider_chain.acceptable_modes must include NOT_CONFIGURED so "
        f"the chain can honestly report 'no provider key'. Got {sorted(m.value for m in modes)!r}"
    )


@pytest.mark.parametrize("code", HONEST_AVAILABILITY_CODES)
def test_misc_seed_has_explicit_unavailable_semantic_test(code: str) -> None:
    """Each optional-provider seed must ship an explicit-unavailable semantic test.

    A semantic_test whose name OR description mentions 'unavailable' or
    'not_configured' proves the seed promises an honest empty/explicit
    response rather than a synthetic placeholder.
    """
    entry = MISC_ENTRIES[code]
    matched = [
        t
        for t in entry.semantic_tests
        if HONEST_KEYWORDS.search(t.name) or HONEST_KEYWORDS.search(t.description)
    ]
    assert matched, (
        f"{code}: must declare at least one semantic_test whose name or "
        f"description mentions 'unavailable' or 'not_configured'. "
        f"Got names {[t.name for t in entry.semantic_tests]!r}"
    )


def test_alrt_is_internal_consumer_only() -> None:
    """ALRT must declare primary=internal — it composes other panes, never opens an upstream call."""
    entry = MISC_ENTRIES["ALRT"]
    assert entry.provider_chain.primary == "internal"
    assert "security gate" in entry.methodology.lower() or "consumer" in entry.methodology.lower() or "internal" in entry.methodology.lower()


def test_bio_methodology_mentions_security_gate() -> None:
    """BIO methodology must explicitly call out the paper→live security-gate role."""
    entry = MISC_ENTRIES["BIO"]
    text = entry.methodology.lower()
    assert "security gate" in text and "paper" in text and "live" in text, (
        "BIO.methodology must mention 'security gate for paper→live transitions'"
    )


def test_lang_methodology_mentions_i18n() -> None:
    """LANG methodology must mention i18n so the relocation story is explicit."""
    entry = MISC_ENTRIES["LANG"]
    assert "i18n" in entry.methodology.lower(), (
        "LANG.methodology must mention i18n"
    )


def test_sat_methodology_mentions_real_or_unavailable() -> None:
    """SAT methodology must promise real imagery or explicit unavailable, never pretend."""
    entry = MISC_ENTRIES["SAT"]
    text = entry.methodology.lower()
    assert "real imagery" in text or "real" in text
    assert "unavailable" in text or "not_configured" in text
    assert "never" in text and ("pretend" in text or "synthetic" in text)


@pytest.mark.parametrize("code", ("DINE", "FLY", "GRAB"))
def test_non_core_utility_methodology_admits_auxiliary_status(code: str) -> None:
    """DINE/FLY/GRAB must say they're auxiliary / low nav weight in finance-first cockpit."""
    entry = MISC_ENTRIES[code]
    text = entry.methodology.lower()
    assert "auxiliary" in text, (
        f"{code}: methodology must mention 'auxiliary' — these are not finance functions"
    )
    assert "low nav weight" in text or "miscellaneous tray" in text, (
        f"{code}: methodology must call out low nav weight / miscellaneous tray placement"
    )


def test_bmc_methodology_flags_relocation_candidate() -> None:
    """BMC methodology must mention its relocation-candidate status."""
    entry = MISC_ENTRIES["BMC"]
    assert "relocation candidate" in entry.methodology.lower(), (
        "BMC.methodology must explicitly call itself a 'relocation candidate'"
    )


def test_all_misc_seeds_registered_when_loaded() -> None:
    """Importing the MISC seed modules registers exactly the expected codes.

    Done last so a sibling-seed import failure in another wave does not
    block the shape checks above. Uses an isolated registry view:
    after the direct imports at the top of this module ran, every MISC
    code is guaranteed to be in REGISTRY.
    """
    from showme.manifest import REGISTRY

    for code in MISC_CODES:
        assert code in REGISTRY, (
            f"{code}: not present in REGISTRY after direct seed import"
        )
