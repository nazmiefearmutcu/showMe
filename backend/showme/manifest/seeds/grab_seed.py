"""GRAB — Screenshot Email (capture plan, draft only).

GRAB prepares a two-step plan: a local screenshot capture and an email
delivery step. It never transmits anything. The handler is
``GRABFunction`` in ``showme.engine.functions.misc._extras``; this seed must
describe that contract, not a shopping list.
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
    ColumnSpec,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def grab() -> FunctionManifest:
    return FunctionManifest(
        code="GRAB",
        name="Screenshot Email",
        category=Category.MISC,
        intent=(
            "Plan a screenshot of the current pane or URL and its email delivery. The plan is "
            "plan only: nothing is captured to a shared location, no draft is created, and nothing is emailed by this function."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="target",
                label="Capture target",
                control=ControlKind.TEXT,
                required=False,
                description="Pane, URL or other capture target. Defaults to the current pane.",
            ),
            InputSpec(
                name="recipient",
                label="Recipient",
                control=ControlKind.TEXT,
                required=False,
                description="Email address the screenshot would be sent to. Only a plan is recorded; no draft is created.",
            ),
            InputSpec(
                name="send",
                label="Send requested",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "Requests delivery. Never executed here: the response records a warning and "
                    "the email step stays planned or not_configured."
                ),
            ),
        ],
        defaults={},
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="step", label="Step", kind="tag"),
                ColumnSpec(key="target", label="Target", kind="text"),
                ColumnSpec(key="status", label="Status", kind="tag"),
                ColumnSpec(key="output", label="Output", kind="text"),
                ColumnSpec(key="transmits_data", label="Sends data", kind="text"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="capture", label="Capture", kind="badge"),
                CardSlot(key="email", label="Email", kind="badge"),
            ],
        ),
        methodology=(
            "GRAB is an auxiliary utility in the miscellaneous tray (low nav weight), not a finance "
            "function. It returns a capture plan with two steps. The capture step is a plan entry only: "
            "no screenshot is taken by this function, and it does not transmit data. The email step is reported as planned when a recipient is given and "
            "not_configured otherwise, and it always carries transmits_data=true as a flag. "
            "A send request is recorded as a warning; no mail is sent automatically, and sending "
            "requires a separately confirmed mail integration."
        ),
        field_dict={
            "rows[].step": FieldDef(description="Capture or delivery phase.", source="computed"),
            "rows[].target": FieldDef(description="Pane, URL or recipient for the phase.", source="input"),
            "rows[].status": FieldDef(description="planned or not_configured.", source="computed"),
            "rows[].transmits_data": FieldDef(description="Whether the phase would share user data outside the app.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=False,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="grab_send_request_never_transmits",
                description="With send=true no mail is transmitted; a warning states that confirmation is required.",
                inputs={"send": True, "recipient": "ops@example.com"},
                assertions=["email_status_is_planned", "warning_states_send_not_executed"],
            ),
            SemanticTest(
                name="grab_email_without_recipient_is_not_configured",
                description="With no recipient the email step reports not_configured and sends nothing.",
                inputs={},
                assertions=["email_status_equals_not_configured"],
            ),
        ],
    )


__all__ = ["grab"]
