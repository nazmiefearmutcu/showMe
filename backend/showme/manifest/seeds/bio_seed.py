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
                description="Reason text for the OS biometric prompt. The BIO pane passes it to the Tauri bridge; this endpoint does not prompt and ignores it.",
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
            must_have=["status", "rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        card_schema=None,
        methodology=(
            "BIO is a security gate for paper→live transitions and other privileged actions. "
            "The sidecar endpoint cannot probe or prompt LocalAuthentication, so it only reports "
            "static reference rows for the host platform (status ready on macOS, unavailable "
            "elsewhere, with a reason). The BIO pane calls the Tauri biometric bridge directly: "
            "capabilities() and requestBiometric(reason) resolve there to {allowed, via, reason}. "
            "When that bridge is missing (browser fallback / non-Mac), the pane gets allowed=False "
            "with via='unavailable' and an explicit warning — BIO never silently approves. No external "
            "provider is involved; verifier history is in-memory only (not persisted)."
        ),
        field_dict={
            "status": FieldDef(description="ready on macOS; unavailable on other hosts (reason is set).", source="local_platform"),
            "rows": FieldDef(description="Static reference rows for capabilities, verify and credential_registry; not a live probe.", source="static_reference_documentation"),
            "host_platform": FieldDef(description="sys.platform of the sidecar host.", source="local_platform"),
            "reason": FieldDef(description="Why verify is denied on this host, when it is.", source="local_platform"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="bio_endpoint_reports_reference_status_without_probe",
                description="The endpoint returns static reference rows and host_platform without probing or prompting the OS; on non-macOS hosts status is unavailable with a reason, never ready.",
                inputs={},
                assertions=[
                    "status_is_ready_or_unavailable",
                    "rows_describe_capabilities_verify_and_registry",
                    "sources_static_reference_documentation",
                    "live_is_false",
                ],
            ),
            SemanticTest(
                name="bio_unavailable_when_no_local_auth_bridge",
                description="Pane-side: if the Tauri biometric bridge is missing (browser / non-Mac), verify resolves allowed=False with via='unavailable' and an explicit not_configured warning — never silently allowed.",
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
                description="Pane-side: a user-denied prompt resolves allowed=False with via='user_cancel'; session counters increment the denied bucket.",
                inputs={"_mock": "user_cancel"},
                assertions=[
                    "allowed_is_false",
                    "session_denied_incremented",
                ],
            ),
        ],
    )


__all__ = ["bio"]
