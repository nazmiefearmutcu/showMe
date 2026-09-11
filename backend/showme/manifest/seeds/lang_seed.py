"""LANG — Language Switch (runtime i18n preference).

Internal preference primitive: persists the selected runtime language
(`runtime/lang.txt`) and reports the 12 supported locales with their
label / selected / coverage / requires_reload flags. No external
provider. Resynced to the shipped handler
(``engine/functions/misc/_extras.py::LANGFunction``) by fix lane F14 —
the previous seed described a two-locale "Locale Switcher" that the
handler never implemented.
"""
from __future__ import annotations

from ..enums import (
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
        name="Language Switch",
        category=Category.MISC,
        intent=(
            "Own the runtime i18n preference: persist the selected language and report the "
            "12 supported locales with coverage + reload flags — no external provider, no "
            "network calls."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="lang",
                label="Language",
                control=ControlKind.SELECT,
                required=True,
                description="Runtime language code persisted to runtime/lang.txt.",
                options=[
                    "tr", "en", "de", "fr", "es", "it",
                    "pt", "ru", "zh", "ja", "ko", "ar",
                ],
            ),
        ],
        defaults={
            "lang": "tr",
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
            must_have=["status", "lang", "rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="lang", label="Selected", kind="badge"),
                CardSlot(key="languages", label="Languages", kind="kpi"),
            ],
        ),
        methodology=(
            "LANG is the runtime i18n preference primitive. The selected language code is "
            "written to runtime/lang.txt; the response echoes it and returns one row per "
            "supported locale (12 today: tr, en, de, fr, es, it, pt, ru, zh, ja, ko, ar) with "
            "the human label, selected flag, current coverage tier, and whether a pane "
            "reload is required for the switch to render. An unsupported code returns "
            "status=input_error with the supported list and an explicit warning instead of "
            "silently falling back. Shell-wide text still depends on preference-aware "
            "surfaces reading the saved value."
        ),
        field_dict={
            "lang": FieldDef(description="IETF-style language code.", source="preference_store"),
            "rows[].label": FieldDef(description="Human-readable language name.", source="catalog"),
            "rows[].selected": FieldDef(description="True for the persisted language.", source="computed"),
            "coverage": FieldDef(description="Translation coverage currently available in ShowMe (core_labels).", source="catalog"),
            "requires_reload": FieldDef(description="Whether the selected preference needs a pane reload to become visible.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=False,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="lang_reports_all_12_supported_locales",
                description="The rows list exactly the 12 handler-supported locales and no others.",
                inputs={},
                assertions=["rows_len_equals_12", "row_codes_match_supported_set"],
            ),
            SemanticTest(
                name="lang_selection_is_flagged_in_rows",
                description="Exactly one row carries selected=true and it matches the requested code.",
                inputs={"lang": "de"},
                assertions=[
                    "exactly_one_selected_row",
                    "selected_row_lang_equals_de",
                ],
            ),
            SemanticTest(
                name="lang_unsupported_code_returns_input_error_with_warning",
                description="An unsupported code returns status=input_error + the supported list + a warning — never a silent fallback.",
                inputs={"lang": "zz"},
                assertions=[
                    "status_equals_input_error",
                    "supported_list_present",
                    "warning_mentions_unsupported_language",
                ],
            ),
        ],
    )


__all__ = ["lang"]
