"""BIO — Biometric unlock for privileged actions.

BIO is a local security primitive: it gates paper→live transitions and
other privileged actions (credential write, bot enable, threshold push)
behind a macOS LocalAuthentication prompt (Touch ID / Apple Watch /
device passcode). It has no external provider — capabilities and verify
calls go through the Tauri biometric bridge.
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
def bio() -> FunctionManifest:
    return FunctionManifest(
        code="BIO",
        name="Biometric Auth",
        category=Category.MISC,
        intent=(
            "Local biometric verification primitive that acts as a security gate for "
            "paper→live transitions and other privileged actions, backed by the macOS "
            "LocalAuthentication framework — no external provider."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="reason",
                label="Prompt reason",
                control=ControlKind.TEXT,
                required=True,
                description="Reason text shown in the OS biometric prompt.",
            ),
            InputSpec(
                name="action",
                label="Action",
                control=ControlKind.SELECT,
                required=False,
                description="What the verify call gates (audit / display only).",
                options=["paper_to_live", "credential_write", "bot_enable", "manual_order", "test"],
            ),
        ],
        defaults={
            "reason": "ShowMe biometric verification",
            "action": "test",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.NOT_CONFIGURED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["allowed", "via"],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="biometry_kind", label="Biometry", kind="badge"),
                CardSlot(key="biometry_available", label="Available", kind="badge"),
                CardSlot(key="passcode_available", label="Passcode", kind="badge"),
                CardSlot(key="last_result", label="Last Verify", kind="mode_pill"),
                CardSlot(key="session_allowed", label="Allowed", kind="kpi"),
                CardSlot(key="session_denied", label="Denied", kind="kpi"),
            ],
        ),
        methodology=(
            "BIO is a security gate for paper→live transitions and other privileged actions. "
            "It exposes two operations: capabilities() returns {biometry_kind, biometry_available, "
            "passcode_available}; requestBiometric(reason) opens the macOS LocalAuthentication "
            "prompt and resolves to {allowed, via, reason}. When the Tauri biometric bridge is "
            "missing (browser fallback / non-Mac), the result is allowed=False with via='unavailable' "
            "and an explicit warning — BIO never silently approves. No external provider is involved; "
            "verifier history is in-memory only (not persisted)."
        ),
        field_dict={
            "allowed": FieldDef(description="True if the OS reported a successful authentication.", source="local_auth"),
            "via": FieldDef(description="touch_id | watch | passcode | unavailable.", source="local_auth"),
            "biometry_kind": FieldDef(description="touch_id | face_id | none — reported by the OS.", source="local_auth"),
            "biometry_available": FieldDef(description="Whether the device has a usable biometry enrolment.", source="local_auth"),
            "passcode_available": FieldDef(description="Whether the device has an owner passcode set.", source="local_auth"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="bio_capabilities_returns_kind_and_flags",
                description="capabilities() returns {biometry_kind, biometry_available, passcode_available} without prompting the user.",
                inputs={},
                assertions=[
                    "result_has_biometry_kind",
                    "result_has_biometry_available_bool",
                    "result_has_passcode_available_bool",
                ],
            ),
            SemanticTest(
                name="bio_unavailable_when_no_local_auth_bridge",
                description="If the Tauri biometric bridge is missing (browser / non-Mac), verify resolves allowed=False with via='unavailable' and an explicit not_configured warning — never silently allowed.",
                inputs={"_env": "no_local_auth_bridge"},
                assertions=[
                    "allowed_is_false",
                    "via_equals_unavailable",
                    "warning_mentions_not_configured",
                    "no_silent_allow",
                ],
            ),
            SemanticTest(
                name="bio_denied_does_not_count_as_allowed",
                description="A user-denied prompt resolves allowed=False with via='user_cancel'; session counters increment the denied bucket.",
                inputs={"_mock": "user_cancel"},
                assertions=[
                    "allowed_is_false",
                    "session_denied_incremented",
                ],
            ),
        ],
    )


__all__ = ["bio"]
