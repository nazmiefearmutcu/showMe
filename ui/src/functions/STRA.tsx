/**
 * STRA — Strategy editor. Sub-system E user surface.
 *
 * Layout: Pane chrome (header actions / body split / provenance footer).
 *  - Left rail  : saved strategies + New (dirty-switch guarded).
 *  - Right side : editor — identity fields, timeframe, indicator refs,
 *                 entry/exit rule builders, position sizing, then
 *                 Save / Preview / Delete with honest disabled reasons.
 *
 * Data path: /api/strategies CRUD + POST /api/strategies/{id}/preview
 * (synthetic random-walk preview — disclosed in the UI), all via
 * `@/lib/strategy-store`.
 */
import {
  useEffect, useState,
  type CSSProperties, type KeyboardEvent, type ReactNode,
} from "react";
import {
  useStrategyStore,
  type IndicatorRef, type Position, type Rule, type StrategySpec,
} from "@/lib/strategy-store";
import { useIndicatorStore } from "@/lib/indicator-store";
import {
  duplicateAliasIndices,
  isKnownTimeframe,
  parseDecimalSafe,
  TIMEFRAMES,
  validateOperand,
} from "@/lib/validators";
import {
  ConfirmDialog, Empty, Field, FieldRow, Pane, PaneBody, PaneFooter,
  PaneHeader, Pill, Skeleton, StatusDivider, StatusSection,
} from "@/design-system";
import {
  FunctionControlGroup, LoadStatePill, RefreshButton,
} from "./function-controls";
import type { LoadState } from "./function-control-state";

const PRICE_FIELDS = ["close", "open", "high", "low", "volume"];

const RULE_KINDS: Rule["kind"][] = [
  "crosses_above", "crosses_below", "greater_than", "less_than", "equals_approximately",
];

/** Fallback used when a draft has no `position` block (legacy or blank). */
const DEFAULT_POSITION: Position = {
  side: "long",
  sizing_kind: "fixed_quote",
  sizing_value: 100,
};

const RULE_GROUP_STYLE: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 10,
};

const SECTION_HEADER_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  flexWrap: "wrap",
  marginBottom: 8,
};

const SECTION_TITLE_STYLE: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "var(--tracking-label)",
  textTransform: "uppercase",
  color: "var(--text-mute)",
};

/** Shared box around a raw <select>/<input> so controls match the ds-field look. */
const CONTROL_BOX_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  minWidth: 0,
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  height: 28,
  padding: "0 8px",
};

const BODY_STYLE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "264px minmax(0, 1fr)",
  padding: 0,
  overflow: "hidden",
  minHeight: 0,
};

const RAIL_STYLE: CSSProperties = {
  borderRight: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  overflowY: "auto",
  padding: 10,
  minWidth: 0,
};

const EDITOR_STYLE: CSSProperties = {
  overflowY: "auto",
  padding: "12px 14px",
  minWidth: 0,
};

/** Round 24 — typed shape for the pending-confirm intent. */
type PendingConfirm =
  | { kind: "dirty-switch"; target: string | "new" }
  | { kind: "delete"; id: string };

export function STRAPane() {
  const list = useStrategyStore((s) => s.strategies);
  const draft = useStrategyStore((s) => s.draft);
  const dirty = useStrategyStore((s) => s.dirty);
  const lastPreview = useStrategyStore((s) => s.lastPreview);
  const error = useStrategyStore((s) => s.error);
  const removing = useStrategyStore((s) => s.removing);
  const loading = useStrategyStore((s) => s.loading);
  const saving = useStrategyStore((s) => s.saving);
  const previewing = useStrategyStore((s) => s.previewing);
  const loadList = useStrategyStore((s) => s.loadList);
  const openNew = useStrategyStore((s) => s.openNew);
  const openExisting = useStrategyStore((s) => s.openExisting);
  const setField = useStrategyStore((s) => s.setDraftField);
  const save = useStrategyStore((s) => s.save);
  const remove = useStrategyStore((s) => s.remove);
  const preview = useStrategyStore((s) => s.preview);

  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);

  const catalogEntries = useIndicatorStore((s) => s.entries);
  const loadCatalog = useIndicatorStore((s) => s.loadCatalog);

  useEffect(() => { loadList(); if (catalogEntries.length === 0) loadCatalog(); },
            [loadList, loadCatalog, catalogEntries.length]);

  const indicators = draft?.indicators ?? [];
  const entryRules = draft?.entry_rules ?? [];
  const exitRules = draft?.exit_rules ?? [];
  const position: Position = { ...DEFAULT_POSITION, ...(draft?.position ?? {}) };

  const operandOptions = dedupeOperands(indicators.map((r) => r.alias)
    .concat(PRICE_FIELDS));

  // H-UI-4 — alias collision detection.
  const aliasDupIndices = duplicateAliasIndices(indicators.map((r) => r.alias));
  const emptyAlias = indicators.some((r) => !r.alias.trim());

  // H-UI-3 — unknown timeframe persisted in saved spec.
  const timeframeUnknown = Boolean(draft && !isKnownTimeframe(draft.timeframe));

  // Client-side mirror of the backend's min_length=1 name rule so an empty
  // name is caught inline instead of after a 400 round-trip.
  const nameMissing = Boolean(draft && (draft.name ?? "").trim().length === 0);

  // Route-layer sizing rules (strategies.py) mirrored client-side.
  const sizingInvalid =
    !(Number.isFinite(position.sizing_value) && position.sizing_value > 0);
  const stopInvalid =
    position.stop_loss_pct != null &&
    !(Number.isFinite(position.stop_loss_pct) && position.stop_loss_pct >= 0);
  const tpInvalid =
    position.take_profit_pct != null &&
    !(Number.isFinite(position.take_profit_pct) && position.take_profit_pct >= 0);

  const saveDisabled =
    saving || !dirty || aliasDupIndices.size > 0 || emptyAlias || timeframeUnknown ||
    nameMissing || sizingInvalid || stopInvalid || tpInvalid;

  // P3 A11Y — explain WHY Save is disabled.
  const saveTitle = saving
    ? "Saving…"
    : nameMissing
      ? "Name is required."
      : emptyAlias
        ? "Indicator aliases cannot be empty."
        : aliasDupIndices.size > 0
          ? "Indicator aliases must be unique."
          : timeframeUnknown
            ? "Invalid timeframe — pick one from the list."
            : sizingInvalid
              ? "Position sizing value must be a positive number."
              : stopInvalid || tpInvalid
                ? "Stop loss / take profit must be non-negative numbers."
                : !dirty
                  ? "No changes to save."
                  : undefined;

  const previewDisabled = !draft?.id || dirty || previewing;
  const previewTitle = previewDisabled
    ? !draft?.id
      ? "Save the strategy before previewing."
      : dirty
        ? "Unsaved changes — save first."
        : "Preview is already running…"
    : undefined;

  const listState: LoadState =
    loading && list.length === 0 ? "loading" : error ? "error" : "ok";

  const handleNew = () => {
    if (dirty) {
      setPendingConfirm({ kind: "dirty-switch", target: "new" });
      return;
    }
    openNew();
  };

  // H-UI-10 — dirty switch guard; clicking the already-open strategy is a
  // no-op (no pointless confirm dialog for nothing to discard).
  const handleSidebarClick = (id: string) => {
    if (draft?.id === id) return;
    if (dirty) {
      setPendingConfirm({ kind: "dirty-switch", target: id });
      return;
    }
    void openExisting(id);
  };

  const addIndicator = () => {
    if (!draft) return;
    const fallbackId = catalogEntries[0]?.id ?? "rsi";
    const refs: IndicatorRef[] = [...indicators,
      { alias: `${fallbackId}_${indicators.length + 1}`, id: fallbackId, params: {} }];
    setField("indicators", refs);
  };

  const nameLabel = (draft?.name ?? "").trim() || "(unnamed draft)";
  const subtitle = draft
    ? `${nameLabel} · ${draft.timeframe ?? "—"}${dirty ? " · unsaved changes" : ""}`
    : "select or create a strategy";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code="STRA"
          title="Strategy editor"
          subtitle={subtitle}
          trailing={
            <FunctionControlGroup>
              {draft && (
                <Pill tone={dirty ? "warn" : "muted"} variant="soft" withDot={false}>
                  {dirty ? "unsaved" : draft.id ? "saved" : "new draft"}
                </Pill>
              )}
              <LoadStatePill state={listState} status={error ? "error" : "ok"} />
              <RefreshButton
                loading={loading}
                onClick={() => void loadList()}
                title="Reload strategy list"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody style={BODY_STYLE}>
          <aside style={RAIL_STYLE} aria-label="Saved strategies">
            <button
              type="button"
              className="btn btn--accent"
              style={{ width: "100%", marginBottom: 10 }}
              onClick={handleNew}
            >
              + New strategy
            </button>
            {list.map((m) => {
              const active = draft?.id === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => handleSidebarClick(m.id)}
                  aria-current={active ? "true" : undefined}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    gap: 6,
                    alignItems: "center",
                    width: "100%",
                    textAlign: "left",
                    padding: "7px 8px",
                    marginBottom: 4,
                    background: active ? "var(--surface-3)" : "transparent",
                    border: "1px solid",
                    borderColor: active ? "var(--border-card)" : "transparent",
                    borderRadius: "var(--radius-md)",
                    cursor: "pointer",
                  }}
                >
                  <span style={{ minWidth: 0 }}>
                    <span style={{
                      display: "block", fontWeight: 600, fontSize: "var(--font-size-sm)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {m.name || "(unnamed)"}
                    </span>
                    <span className="u-text-secondary"
                          style={{ fontSize: "var(--font-size-2xs)" }}>
                      {m.timeframe}
                    </span>
                  </span>
                  {active && dirty && (
                    <Pill tone="warn" variant="soft" withDot={false}>*</Pill>
                  )}
                </button>
              );
            })}
            {/* P5 — loading placeholder while the list is in flight + empty. */}
            {loading && list.length === 0 && (
              <div data-testid="stra-list-loading" aria-busy="true"
                   style={{ display: "grid", gap: 8, padding: 4 }}>
                <Skeleton height={30} />
                <Skeleton height={30} />
                <Skeleton height={30} />
              </div>
            )}
            {/* P5 — clear empty-state + CTA when there are no strategies. */}
            {!loading && list.length === 0 && (
              <div data-testid="stra-list-empty">
                <Empty
                  title="No strategies yet"
                  body="Create your first strategy with + New strategy above."
                />
              </div>
            )}
          </aside>

          <div style={EDITOR_STYLE}>
            {!draft && (
              <Empty
                title="No strategy selected"
                body={
                  <span>
                    Pick a strategy from the list on the left, or create one
                    with <strong>+ New strategy</strong>.
                  </span>
                }
                action={
                  <button type="button" className="btn btn--accent" onClick={handleNew}>
                    Create strategy
                  </button>
                }
              />
            )}

            {draft && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
                {/* Action row — Save / Preview / Delete with honest reasons. */}
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="btn btn--accent"
                    data-testid="stra-save-button"
                    onClick={() => {
                      // Round 24 CRITICAL 2 — local short-circuit; the
                      // store-level `if (get().saving) return null` is the seal.
                      if (saving) return;
                      void save();
                    }}
                    disabled={saveDisabled}
                    title={saveTitle}
                  >
                    {saving ? "Saving…" : "Save"}
                  </button>
                  <span title={previewTitle} style={{ display: "inline-flex" }}>
                    <button
                      type="button"
                      className="btn"
                      data-testid="stra-preview-button"
                      aria-busy={previewing || undefined}
                      onClick={() => {
                        if (previewing || !draft.id || dirty) return;
                        void preview(draft.id);
                      }}
                      disabled={previewDisabled}
                    >
                      {previewing ? "Loading…" : "Preview"}
                    </button>
                  </span>
                  {(!draft.id || dirty) && (
                    <span
                      data-testid="stra-preview-hint"
                      className="u-text-secondary"
                      style={{ fontSize: "var(--font-size-sm)", alignSelf: "center" }}
                    >
                      {!draft.id ? "(save before preview)" : "(save first)"}
                    </span>
                  )}
                  {draft.id && (
                    <button
                      type="button"
                      className="btn btn--ghost"
                      data-testid="stra-sil-button"
                      aria-label="Delete strategy"
                      disabled={removing}
                      onClick={() => {
                        if (removing) return;
                        setPendingConfirm({ kind: "delete", id: draft.id! });
                      }}
                      style={{ marginLeft: "auto", color: "var(--negative)" }}
                    >
                      {removing ? "Deleting…" : "Delete"}
                    </button>
                  )}
                </div>

                {error && (
                  <div
                    data-testid="stra-pane-error"
                    role="alert"
                    style={{
                      color: "var(--negative)",
                      border: "1px solid var(--border-card)",
                      background: "var(--surface-2)",
                      borderRadius: "var(--radius-md)",
                      padding: "6px 8px",
                      fontSize: "var(--font-size-sm)",
                    }}
                  >
                    {formatPydanticError(error)}
                  </div>
                )}

                {/* Identity — Name / Timeframe / Description. */}
                <FieldRow>
                  <Field
                    label="Name"
                    value={draft.name ?? ""}
                    onChange={(e) => setField("name", e.target.value)}
                    placeholder="e.g. RSI mean-revert"
                    aria-invalid={nameMissing || undefined}
                    data-testid="stra-name-input"
                  />
                  <SelectField
                    label="Timeframe"
                    value={draft.timeframe ?? "1h"}
                    onChange={(v) => setField("timeframe", v as StrategySpec["timeframe"])}
                  >
                    {/* H-UI-3 — surface unknown timeframes. */}
                    {timeframeUnknown && draft.timeframe && (
                      <option value={draft.timeframe}
                              data-testid="stra-timeframe-unknown-option">
                        [unknown] {draft.timeframe}
                      </option>
                    )}
                    {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </SelectField>
                </FieldRow>
                {nameMissing && (
                  <div data-testid="stra-field-err-name" className="u-text-negative"
                       style={{ fontSize: "var(--font-size-sm)" }}>
                    Name is required.
                  </div>
                )}
                {timeframeUnknown && (
                  <div data-testid="stra-field-err-timeframe" className="u-text-negative"
                       style={{ fontSize: "var(--font-size-sm)" }}>
                    Unknown timeframe: "{draft.timeframe}". Pick one from the list.
                  </div>
                )}
                <Field
                  label="Description"
                  value={draft.description ?? ""}
                  onChange={(e) => setField("description", e.target.value)}
                  placeholder="Optional — what edge does this strategy capture?"
                />

                {/* Indicators. */}
                <section data-testid="stra-indicators-group" style={RULE_GROUP_STYLE}>
                  <div style={SECTION_HEADER_STYLE}>
                    <span style={SECTION_TITLE_STYLE}>Indicators ({indicators.length})</span>
                    <button type="button" className="btn" data-testid="stra-add-indicator"
                            onClick={addIndicator}>
                      + Add indicator
                    </button>
                  </div>
                  <div style={{ display: "grid", gap: 6 }}>
                    {indicators.map((r, idx) => {
                      const isDup = aliasDupIndices.has(idx);
                      const aliasEmpty = !r.alias.trim();
                      return (
                        <div key={idx} style={{
                          display: "grid",
                          gridTemplateColumns: "minmax(100px, 1fr) minmax(140px, 1.2fr) auto",
                          gap: 6, alignItems: "center",
                        }}>
                          <div style={{
                            ...CONTROL_BOX_STYLE,
                            borderColor: isDup || aliasEmpty
                              ? "var(--negative)" : "var(--border-subtle)",
                          }}>
                            <input
                              className="ds-field__input"
                              value={r.alias}
                              onChange={(e) => {
                                const refs = [...indicators];
                                refs[idx] = { ...refs[idx], alias: e.target.value };
                                setField("indicators", refs);
                              }}
                              title={isDup
                                ? "Alias is already used by another indicator — it must be unique."
                                : aliasEmpty
                                  ? "Alias cannot be empty."
                                  : undefined}
                              data-testid={`stra-indicator-alias-${idx}`}
                              data-dup={isDup ? "1" : undefined}
                              aria-label={`indicator-alias-${idx}`}
                            />
                          </div>
                          <div style={CONTROL_BOX_STYLE}>
                            <select
                              className="ds-field__input"
                              value={r.id}
                              onChange={(e) => {
                                const refs = [...indicators];
                                refs[idx] = { ...refs[idx], id: e.target.value };
                                setField("indicators", refs);
                              }}
                              aria-label={`Indicator type ${r.alias || idx}`}
                            >
                              {catalogEntries.map((c) => (
                                <option key={c.id} value={c.id}>{c.display_name}</option>
                              ))}
                              {!catalogEntries.some((c) => c.id === r.id) && (
                                <option value={r.id}>{r.id}</option>
                              )}
                            </select>
                          </div>
                          <button
                            type="button"
                            className="btn btn--ghost"
                            aria-label={`Remove indicator ${r.alias || idx}`}
                            title="Remove indicator"
                            onClick={() => {
                              const refs = indicators.filter((_, i) => i !== idx);
                              setField("indicators", refs);
                            }}
                          >
                            ×
                          </button>
                        </div>
                      );
                    })}
                  </div>
                  {emptyAlias && (
                    <div data-testid="stra-field-err-alias-empty" className="u-text-negative"
                         style={{ fontSize: "var(--font-size-sm)", marginTop: 6 }}>
                      Indicator aliases cannot be empty.
                    </div>
                  )}
                  {aliasDupIndices.size > 0 && (
                    <div data-testid="stra-field-err-alias-dup" className="u-text-negative"
                         style={{ fontSize: "var(--font-size-sm)", marginTop: 6 }}>
                      Indicator aliases must be unique.
                    </div>
                  )}
                  {catalogEntries.length === 0 && (
                    <div data-testid="stra-catalog-note" className="u-text-mute"
                         style={{ fontSize: "var(--font-size-sm)", marginTop: 6 }}>
                      Indicator catalog is empty — new indicators fall back to id
                      "rsi". Refresh the pane or check the sidecar connection.
                    </div>
                  )}
                </section>

                {/* Entry rules. */}
                <section data-testid="stra-entry-group" style={RULE_GROUP_STYLE}>
                  <div style={SECTION_HEADER_STYLE}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      <span style={SECTION_TITLE_STYLE}>
                        Entry rules ({entryRules.length})
                      </span>
                      <span className="u-text-secondary"
                            style={{ fontSize: "var(--font-size-sm)" }}>logic</span>
                      <span style={{ ...CONTROL_BOX_STYLE, height: 24 }}>
                        <select
                          className="ds-field__input"
                          value={draft.entry_logic ?? "all"}
                          aria-label="Entry logic"
                          onChange={(e) => setField("entry_logic", e.target.value as "all" | "any")}
                        >
                          <option value="all">all</option>
                          <option value="any">any</option>
                        </select>
                      </span>
                    </span>
                  </div>
                  <RulesEditor
                    rules={entryRules}
                    onChange={(v) => setField("entry_rules", v)}
                    operandOptions={operandOptions}
                    testIdPrefix="stra-entry"
                  />
                </section>

                {/* Exit rules. */}
                <section data-testid="stra-exit-group" style={RULE_GROUP_STYLE}>
                  <div style={SECTION_HEADER_STYLE}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      <span style={SECTION_TITLE_STYLE}>
                        Exit rules ({exitRules.length})
                      </span>
                      <span className="u-text-secondary"
                            style={{ fontSize: "var(--font-size-sm)" }}>logic</span>
                      <span style={{ ...CONTROL_BOX_STYLE, height: 24 }}>
                        <select
                          className="ds-field__input"
                          value={draft.exit_logic ?? "any"}
                          aria-label="Exit logic"
                          onChange={(e) => setField("exit_logic", e.target.value as "all" | "any")}
                        >
                          <option value="all">all</option>
                          <option value="any">any</option>
                        </select>
                      </span>
                    </span>
                  </div>
                  <RulesEditor
                    rules={exitRules}
                    onChange={(v) => setField("exit_rules", v)}
                    operandOptions={operandOptions}
                    testIdPrefix="stra-exit"
                  />
                </section>

                {/* Position sizing — part of the saved spec contract. */}
                <section data-testid="stra-position-group" style={RULE_GROUP_STYLE}>
                  <div style={SECTION_HEADER_STYLE}>
                    <span style={SECTION_TITLE_STYLE}>Position</span>
                    {sizingInvalid && (
                      <span data-testid="stra-field-err-sizing" className="u-text-negative"
                            style={{ fontSize: "var(--font-size-sm)" }}>
                        Sizing value must be a positive number.
                      </span>
                    )}
                  </div>
                  <PositionEditor
                    position={position}
                    draftId={draft.id ?? null}
                    onPatch={(patch) => setField("position", { ...position, ...patch })}
                  />
                </section>

                {/* Preview result (synthetic-disclosed). */}
                {lastPreview && (
                  <section data-testid="stra-preview-group" style={RULE_GROUP_STYLE}>
                    <div style={SECTION_HEADER_STYLE}>
                      <span style={SECTION_TITLE_STYLE}>
                        Preview — {lastPreview.bars} bars · {lastPreview.source}
                      </span>
                    </div>
                    {/* P1 DATA HONESTY — only warn when the backend says the
                        data is synthetic. */}
                    {isSyntheticSource(lastPreview.source) && (
                      <div
                        data-testid="stra-preview-synthetic-note"
                        role="note"
                        style={{
                          color: "var(--text-secondary)",
                          fontSize: "var(--font-size-sm)",
                          margin: "0 0 6px",
                          padding: "4px 8px",
                          border: "1px solid var(--border-card)",
                          borderRadius: "var(--radius-md)",
                          background: "var(--surface-3)",
                        }}
                      >
                        ⚠ Preview runs on synthetic random-walk data — validates
                        whether rules fire, NOT real market performance.
                      </div>
                    )}
                    <ul style={{
                      listStyle: "none", margin: 0, padding: 0,
                      display: "grid", gap: 2,
                      fontFamily: "var(--font-mono)", fontSize: "var(--font-size-sm)",
                    }}>
                      {lastPreview.events.slice(0, 30).map((e, i) => (
                        <li key={i} style={{
                          display: "grid",
                          gridTemplateColumns: "56px 92px 56px 1fr",
                          gap: 8,
                        }}>
                          <span className="u-text-mute">[{e.bar_index}]</span>
                          <span className="u-text-secondary">{e.bar_time}</span>
                          <strong>{e.kind}</strong>
                          <span className="terminal-grid-numeric">
                            {e.price.toFixed(2)}
                          </span>
                        </li>
                      ))}
                      {lastPreview.events.length === 0 && (
                        <li className="u-text-secondary">(no events)</li>
                      )}
                    </ul>
                    {lastPreview.events.length > 30 && (
                      <div
                        data-testid="stra-preview-truncated"
                        className="u-text-mute"
                        style={{ fontSize: "var(--font-size-sm)", marginTop: 6 }}
                      >
                        Showing first 30 of {lastPreview.events.length} events.
                      </div>
                    )}
                  </section>
                )}
              </div>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="strategy"
            value={draft?.id ? draft.id.slice(0, 8) : "unsaved draft"}
          />
          <StatusDivider />
          <StatusSection
            label="timeframe"
            value={draft?.timeframe ?? "—"}
            tone={timeframeUnknown ? "negative" : "neutral"}
          />
          <StatusDivider />
          <StatusSection label="indicators" value={indicators.length} />
          <StatusDivider />
          <StatusSection label="rules" value={entryRules.length + exitRules.length} />
          <StatusDivider />
          <StatusSection label="api" value="/api/strategies" tone="muted" />
        </PaneFooter>
      </Pane>

      {/* Round 24 — non-blocking confirm dialog for delete + dirty-switch. */}
      <ConfirmDialog
        open={pendingConfirm !== null}
        title={pendingConfirm?.kind === "delete"
          ? "Delete strategy"
          : "Unsaved changes"}
        body={pendingConfirm?.kind === "delete"
          ? "Are you sure you want to delete this strategy? Bots attached to it may be affected."
          : "Unsaved changes will be lost. Continue?"}
        confirmLabel={pendingConfirm?.kind === "delete" ? "Delete" : "Continue"}
        destructive={pendingConfirm?.kind === "delete"}
        busy={removing}
        onConfirm={() => {
          if (!pendingConfirm) return;
          if (pendingConfirm.kind === "delete") {
            void remove(pendingConfirm.id, { skipConfirm: true });
          } else if (pendingConfirm.kind === "dirty-switch") {
            if (pendingConfirm.target === "new") openNew();
            else void openExisting(pendingConfirm.target);
          }
          setPendingConfirm(null);
        }}
        onCancel={() => setPendingConfirm(null)}
      />
    </div>
  );
}

/**
 * A labelled <select> styled with the shared ds-field classes (Field only
 * wraps <input>). Keeps the label/select semantics the tests rely on.
 */
function SelectField({
  label, value, onChange, error, errorTestId, children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  errorTestId?: string;
  children: ReactNode;
}) {
  return (
    <label className="ds-field">
      <span className="ds-field__label">{label}</span>
      <div className="ds-field__row">
        <select
          className="ds-field__input"
          value={value}
          aria-label={label}
          onChange={(e) => onChange(e.target.value)}
        >
          {children}
        </select>
      </div>
      {error && (
        <span className="ds-field__hint" data-testid={errorTestId}
              style={{ color: "var(--negative)" }}>
          {error}
        </span>
      )}
    </label>
  );
}

/**
 * Position sizing editor. Numeric fields keep a local raw string so a
 * half-typed value never corrupts the draft; the parsed value commits on
 * blur / Enter and reverts when unparsable.
 */
function PositionEditor({
  position, onPatch, draftId,
}: {
  position: Position;
  onPatch: (patch: Partial<Position>) => void;
  draftId: string | null;
}) {
  const [sizingRaw, setSizingRaw] = useState<string>(
    () => (position.sizing_value == null ? "" : String(position.sizing_value)));
  const [stopRaw, setStopRaw] = useState<string>(
    () => (position.stop_loss_pct == null ? "" : String(position.stop_loss_pct)));
  const [tpRaw, setTpRaw] = useState<string>(
    () => (position.take_profit_pct == null ? "" : String(position.take_profit_pct)));

  useEffect(() => {
    setSizingRaw(position.sizing_value == null ? "" : String(position.sizing_value));
    setStopRaw(position.stop_loss_pct == null ? "" : String(position.stop_loss_pct));
    setTpRaw(position.take_profit_pct == null ? "" : String(position.take_profit_pct));
    // Reset only when the edited strategy identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftId]);

  const commitSizing = () => {
    const parsed = parseDecimalSafe(sizingRaw);
    if (parsed.ok && parsed.value > 0) onPatch({ sizing_value: parsed.value });
    else setSizingRaw(position.sizing_value == null ? "" : String(position.sizing_value));
  };
  const commitStop = () => {
    if (stopRaw.trim() === "") {
      onPatch({ stop_loss_pct: null });
      return;
    }
    const parsed = parseDecimalSafe(stopRaw);
    if (parsed.ok && parsed.value >= 0) onPatch({ stop_loss_pct: parsed.value });
    else setStopRaw(position.stop_loss_pct == null ? "" : String(position.stop_loss_pct));
  };
  const commitTp = () => {
    if (tpRaw.trim() === "") {
      onPatch({ take_profit_pct: null });
      return;
    }
    const parsed = parseDecimalSafe(tpRaw);
    if (parsed.ok && parsed.value >= 0) onPatch({ take_profit_pct: parsed.value });
    else setTpRaw(position.take_profit_pct == null ? "" : String(position.take_profit_pct));
  };
  const blurOnEnter = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
  };

  const sizingHint = position.sizing_kind === "risk_pct"
    ? "percent of equity (1–100)"
    : position.sizing_kind === "fixed_base"
      ? "base units (e.g. 0.05)"
      : "quote amount (e.g. 500)";

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
      gap: 10,
    }}>
      <SelectField
        label="Side"
        value={position.side}
        onChange={(v) => onPatch({ side: v as Position["side"] })}
      >
        <option value="long">long</option>
        <option value="short">short</option>
      </SelectField>
      <SelectField
        label="Sizing kind"
        value={position.sizing_kind}
        onChange={(v) => onPatch({ sizing_kind: v as Position["sizing_kind"] })}
      >
        <option value="fixed_quote">fixed_quote</option>
        <option value="fixed_base">fixed_base</option>
        <option value="risk_pct">risk_pct</option>
      </SelectField>
      <Field
        label="Sizing value"
        value={sizingRaw}
        onChange={(e) => setSizingRaw(e.target.value)}
        onBlur={commitSizing}
        onKeyDown={blurOnEnter}
        inputMode="decimal"
        hint={sizingHint}
        aria-label="Sizing value"
        data-testid="stra-position-sizing"
      />
      <Field
        label="Stop loss %"
        value={stopRaw}
        onChange={(e) => setStopRaw(e.target.value)}
        onBlur={commitStop}
        onKeyDown={blurOnEnter}
        inputMode="decimal"
        placeholder="optional"
        aria-label="Stop loss percent"
        data-testid="stra-position-stop"
      />
      <Field
        label="Take profit %"
        value={tpRaw}
        onChange={(e) => setTpRaw(e.target.value)}
        onBlur={commitTp}
        onKeyDown={blurOnEnter}
        inputMode="decimal"
        placeholder="optional"
        aria-label="Take profit percent"
        data-testid="stra-position-tp"
      />
    </div>
  );
}

/**
 * Avoid duplicate React keys when the user temporarily has duplicate
 * indicator aliases — each operand is shown exactly once in the rule
 * dropdowns; the alias-collision UI surfaces the underlying problem.
 */
function dedupeOperands(operands: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const o of operands) {
    if (!seen.has(o)) {
      seen.add(o);
      out.push(o);
    }
  }
  return out;
}

/**
 * P1 DATA HONESTY — is the preview's data source synthetic?
 *
 * The backend currently returns "synthetic_random_walk" (POST /preview runs
 * a seeded random walk, NOT real market data). We key off the substring so a
 * future real-OHLCV source (e.g. "exchange_ohlcv") does NOT trip the warning.
 */
function isSyntheticSource(source: string | undefined): boolean {
  return typeof source === "string" && source.toLowerCase().includes("synthetic");
}

/**
 * Best-effort Pydantic 422 detail formatter. Falls through to the raw
 * string when the payload isn't JSON.
 */
function formatPydanticError(raw: string): string {
  if (!raw) return raw;
  const m = raw.match(/\{[\s\S]*\}$/);
  if (!m) return raw;
  try {
    const body = JSON.parse(m[0]);
    const detail = body?.detail;
    if (Array.isArray(detail) && detail.length) {
      return detail
        .map((d: { loc?: unknown; msg?: string }) => {
          const loc = Array.isArray(d.loc) ? d.loc.join(".") : String(d.loc ?? "");
          return `${loc}: ${d.msg ?? ""}`.trim();
        })
        .join("; ");
    }
    if (typeof detail === "string") return detail;
  } catch {
    /* fall through */
  }
  return raw;
}

function RulesEditor({
  rules, onChange, operandOptions, testIdPrefix,
}: {
  rules: Rule[];
  onChange: (rs: Rule[]) => void;
  operandOptions: string[];
  testIdPrefix?: string;
}) {
  return (
    <div>
      <button
        type="button"
        className="btn"
        data-testid={testIdPrefix ? `${testIdPrefix}-add-rule` : undefined}
        onClick={() => onChange([...rules,
          { kind: "greater_than", left: "close", right: "literal:0" }])}
      >
        + Add rule
      </button>
      <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
        {rules.map((r, idx) => {
          const rightError = validateOperand(r.right, operandOptions);
          return (
            <div key={idx} style={{
              display: "grid",
              gridTemplateColumns: "minmax(110px, 150px) minmax(130px, 170px) minmax(120px, 1fr) auto",
              gap: 6,
              alignItems: "center",
            }}>
              <div style={CONTROL_BOX_STYLE}>
                <select
                  className="ds-field__input"
                  value={r.left}
                  onChange={(e) => {
                    const next = [...rules];
                    next[idx] = { ...next[idx], left: e.target.value };
                    onChange(next);
                  }}
                  aria-label={`rule-${idx}-left`}
                >
                  {!operandOptions.includes(r.left) && (
                    <option value={r.left}>[unknown] {r.left}</option>
                  )}
                  {operandOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
              <div style={CONTROL_BOX_STYLE}>
                <select
                  className="ds-field__input"
                  value={r.kind}
                  onChange={(e) => {
                    const next = [...rules];
                    next[idx] = { ...next[idx], kind: e.target.value as Rule["kind"] };
                    onChange(next);
                  }}
                  aria-label={`Rule ${idx} operator`}
                >
                  {RULE_KINDS.map((k) => (
                    <option key={k} value={k}>{k.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </div>
              <div style={{
                ...CONTROL_BOX_STYLE,
                borderColor: rightError ? "var(--negative)" : "var(--border-subtle)",
              }}>
                <input
                  className="ds-field__input terminal-grid-numeric"
                  value={r.right}
                  onChange={(e) => {
                    const next = [...rules];
                    next[idx] = { ...next[idx], right: e.target.value };
                    onChange(next);
                  }}
                  placeholder="literal:30 or alias"
                  aria-label={`rule-${idx}-right`}
                  title={rightError ?? undefined}
                  data-testid={testIdPrefix ? `${testIdPrefix}-rule-${idx}-right` : undefined}
                />
              </div>
              <button
                type="button"
                className="btn btn--ghost"
                aria-label={`Remove rule ${idx}`}
                title="Remove rule"
                onClick={() => onChange(rules.filter((_, i) => i !== idx))}
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
      {rules.some((r) => validateOperand(r.right, operandOptions)) && (
        <div
          data-testid={testIdPrefix ? `${testIdPrefix}-operand-hint` : undefined}
          className="u-text-negative"
          style={{ fontSize: "var(--font-size-sm)", marginTop: 6 }}
        >
          Use a "literal:" prefix for numbers (e.g. literal:30).
        </div>
      )}
    </div>
  );
}

export default STRAPane;
