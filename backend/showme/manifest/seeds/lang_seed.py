"""LANG — Locale switcher (en / tr).

LANG is an internal preference primitive: it owns the active UI locale
(en / tr) and persists the choice across launches. No external provider
is involved; LANG only writes to local preference storage and broadcasts
the change to subscribers via the i18n bus.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    CardSchema,
    CardSlot,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def lang() -> FunctionManifest:
    return FunctionManifest(
        code="LANG",
        name="Locale Switcher",
        category=Category.MISC,
        intent=(
            "Local i18n preference primitive that owns the active UI locale (en / tr), "
            "persists the choice across launches, and broadcasts the change to subscribers — "
            "no external provider, no network calls."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="locale",
                label="Locale",
                control=ControlKind.SELECT,
                required=True,
                description="Active UI locale code.",
                options=["en", "tr"],
            ),
        ],
        defaults={
            "locale": "en",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="global", persist=True),
        output_contract=OutputContract(
            must_have=["locale"],
            rows=False,
            series=False,
            cards=True,
            warnings=False,
            next_actions=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="locale", label="Locale", kind="badge"),
                CardSlot(key="locale_name", label="Name", kind="badge"),
            ],
        ),
        methodology=(
            "LANG owns the i18n state. The locale code is stored in local preference storage "
            "(Round 16 preset filesystem on Tauri / localStorage in browser) and emitted on the "
            "i18n bus that ShowMe components subscribe to for label translations. The only "
            "supported locales today are 'en' and 'tr'; an unknown code falls back to 'en' with "
            "an explicit warning rather than rendering raw keys. There is no external "
            "translation service — strings live in the bundled message catalog."
        ),
        field_dict={
            "locale": FieldDef(description="Active locale code (en / tr).", source="preference_store"),
            "locale_name": FieldDef(description="Human-readable locale label (English / Türkçe).", source="catalog"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="lang_default_is_english",
                description="With no prior preference stored, locale resolves to 'en'.",
                inputs={},
                assertions=["locale_equals_en"],
            ),
            SemanticTest(
                name="lang_switch_to_tr_persists",
                description="Switching to 'tr' persists the choice so reload returns 'tr' without re-prompt.",
                inputs={"locale": "tr"},
                assertions=[
                    "locale_equals_tr_after_set",
                    "locale_equals_tr_after_reload",
                ],
            ),
            SemanticTest(
                name="lang_unknown_locale_falls_back_with_warning",
                description="An unsupported locale code falls back to 'en' and surfaces a warning, never renders raw keys.",
                inputs={"locale": "zz"},
                assertions=[
                    "locale_equals_en_after_unknown",
                    "warning_mentions_unsupported_locale",
                ],
            ),
        ],
    )


__all__ = ["lang"]
