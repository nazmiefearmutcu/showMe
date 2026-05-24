import { useEffect, useMemo, useRef, useState } from "react";
import {
  Empty,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Skeleton,
} from "@/design-system";
import {
  FunctionCallError,
  runFunction,
  type FunctionCallResult,
} from "@/lib/functions";
import { useAppStore } from "@/lib/store";
import {
  assetClassForFunctionSymbol,
  defaultSymbolForFunction,
  normalizeSymbolInput,
  pushRecentSymbol,
  quickSymbolsForFunction,
} from "@/lib/symbols";
import { isSymbolFirstFunction } from "@/functions/symbol-first";
import { useWorkspace } from "@/lib/workspace";
import {
  FunctionControlGroup,
  LoadStatePill,
  RowLimitControl,
  SegmentedControl,
} from "@/functions/function-controls";
import {
  ROW_LIMITS,
  type RowLimit,
  usePersistentOption,
} from "@/functions/function-control-state";
import type { FunctionEntry } from "@/lib/sidecar";
import { setLocale, type Locale } from "@/i18n";
import {
  STUB_RANGES,
  STUB_RANGE_IDS,
  type BacktestStrategy,
  type LoadState,
  type MLHorizon,
  type OptionStrategy,
  type OptionType,
  type StubRangeId,
  type TicketSide,
  type TicketTif,
  type TicketType,
} from "./_types";
import {
  buildControlParams,
  buildControlProfile,
  buildBacktestControlParams,
  buildOptionControlParams,
  buildOptionDefaultsForFunction,
  buildSimpleControlParams,
  defaultBacktestStrategyForFunction,
  defaultQueryForFunction,
  defaultRuntimeParams,
  defaultSimpleParamsForFunction,
  functionTimeoutMs,
  paramsPlaceholder,
  simpleParamSpecsForFunction,
} from "./params";
import {
  compatibleRequestedSymbol,
  getPayloadStatus,
  mergeParams,
  parseParams,
  suggestedSymbolsForFunction,
  summarizeResult,
} from "./helpers";
import {
  BacktestControls,
  MLSignalControls,
  OptionAssumptionControls,
  SimpleParamControls,
  TradeTicketControls,
} from "./controls";
import {
  FunctionHelp,
  GenericResult,
} from "./panels";
import {
  advancedHeader,
  advancedPanel,
  codeLine,
  commandActions,
  commandBar,
  controlInlinePanel,
  functionBody,
  functionIdentity,
  identityMeta,
  metaLabel,
  quickRow,
  resultPane,
  scopeBlock,
  symbolTools,
  textareaStyle,
} from "./styles";

export function FunctionStub({
  leafId,
  code,
  symbol,
}: {
  leafId?: string;
  code: string;
  symbol?: string;
}) {
  const upperCode = code.toUpperCase();
  const setLeafTarget = useWorkspace((s) => s.setLeafTarget);
  const idx = useAppStore((s) => s.functionIndex);
  const entry = useMemo<FunctionEntry | null>(
    () => idx.find((f) => f.code === upperCode) ?? null,
    [idx, upperCode],
  );
  const [inputSymbol, setInputSymbol] = useState(symbol ?? "");
  const [state, setState] = useState<LoadState>("idle");
  const [result, setResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paramsText, setParamsText] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const symbolFirst = isSymbolFirstFunction(upperCode, entry?.category);
  const assetClasses = entry?.asset_classes ?? [];
  const assetClassKey = assetClasses.join("|");
  const defaultRunSymbol = defaultSymbolForFunction(upperCode, assetClasses);
  const quickSymbols = quickSymbolsForFunction(upperCode, assetClasses);
  const effectiveSymbol = symbolFirst
    ? normalizeSymbolInput(inputSymbol) || defaultRunSymbol
    : "";
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    `showme.stub.${upperCode}.limit`,
    ROW_LIMITS,
    50,
  );
  const defaultRange = upperCode === "SAT" ? "1M" : "1Y";
  const [range, setRange] = usePersistentOption<StubRangeId>(
    `showme.stub.${upperCode}.range`,
    STUB_RANGE_IDS,
    defaultRange,
  );
  const controlProfile = useMemo(
    () => buildControlProfile(upperCode, entry?.category),
    [upperCode, entry?.category],
  );
  const [queryText, setQueryText] = useState(() => defaultQueryForFunction(upperCode, entry?.category));
  const [transcriptText, setTranscriptText] = useState("");
  const [ticketSide, setTicketSide] = useState<TicketSide>("BUY");
  const [ticketQuantity, setTicketQuantity] = useState("1");
  const [ticketType, setTicketType] = useState<TicketType>("MARKET");
  const [ticketTif, setTicketTif] = useState<TicketTif>("DAY");
  const [optionSpot, setOptionSpot] = useState("100");
  const [optionStrike, setOptionStrike] = useState("105");
  const [optionShortStrike, setOptionShortStrike] = useState("110");
  const [optionExpiry, setOptionExpiry] = useState("0.25");
  const [optionVol, setOptionVol] = useState("0.28");
  const [optionRate, setOptionRate] = useState("0.045");
  const [optionType, setOptionType] = useState<OptionType>("CALL");
  const [optionStrategy, setOptionStrategy] = useState<OptionStrategy>("CALL_SPREAD");
  const [backtestStrategy, setBacktestStrategy] = useState<BacktestStrategy>("ALL");
  const [mlHorizon, setMlHorizon] = useState<MLHorizon>("1");
  const [simpleParams, setSimpleParams] = useState<Record<string, string>>(
    () => defaultSimpleParamsForFunction(upperCode),
  );
  const optionControls = upperCode === "OVME" || upperCode === "OSA";
  const backtestControls = upperCode === "BTFW" || upperCode === "BMTX" || upperCode === "BTUNE";
  const mlSignalControls = upperCode === "MLSIG";
  const simpleControlSpecs = useMemo(() => simpleParamSpecsForFunction(upperCode), [upperCode]);
  const optionControlParams = useMemo(
    () => buildOptionControlParams(
      upperCode,
      optionSpot,
      optionStrike,
      optionShortStrike,
      optionExpiry,
      optionVol,
      optionRate,
      optionType,
      optionStrategy,
    ),
    [
      upperCode,
      optionSpot,
      optionStrike,
      optionShortStrike,
      optionExpiry,
      optionVol,
      optionRate,
      optionType,
      optionStrategy,
    ],
  );
  const backtestControlParams = useMemo(
    () => buildBacktestControlParams(upperCode, backtestStrategy),
    [upperCode, backtestStrategy],
  );
  const mlSignalControlParams = useMemo(
    () => (upperCode === "MLSIG" ? { horizon: Number(mlHorizon) } : {}),
    [upperCode, mlHorizon],
  );
  const simpleControlParams = useMemo(
    () => buildSimpleControlParams(upperCode, simpleParams),
    [upperCode, simpleParams],
  );
  const controlParams = useMemo(
    () => ({
      ...buildControlParams(controlProfile, limit, range, queryText),
      ...optionControlParams,
      ...backtestControlParams,
      ...mlSignalControlParams,
      ...simpleControlParams,
      ...(controlProfile.transcriptText && transcriptText.trim()
        ? { text: transcriptText.trim() }
        : {}),
      ...(controlProfile.tradeTicket
        ? {
            side: ticketSide,
            quantity: Number(ticketQuantity) || 0,
            type: ticketType,
            tif: ticketTif,
            submit: false,
          }
        : {}),
    }),
    [
      controlProfile,
      limit,
      range,
      queryText,
      optionControlParams,
      backtestControlParams,
      mlSignalControlParams,
      simpleControlParams,
      transcriptText,
      ticketSide,
      ticketQuantity,
      ticketType,
      ticketTif,
    ],
  );
  const internalSymbolSync = useRef<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const controlsReady = useRef(false);
  const lastFingerprintRef = useRef<string>("");

  const load = async (
    signal?: AbortSignal,
    runSymbol = effectiveSymbol,
    paramsOverride?: Record<string, unknown>,
  ) => {
    const normalizedSymbol = symbolFirst
      ? compatibleRequestedSymbol(
          runSymbol || inputSymbol || defaultRunSymbol,
          entry,
        ) || defaultRunSymbol
      : "";
    const runAssetClass = symbolFirst
      ? assetClassForFunctionSymbol(normalizedSymbol, assetClasses)
      : undefined;

    const params = {
      ...defaultRuntimeParams(upperCode),
      ...(paramsOverride ?? controlParams),
      ...(parseParams(paramsText) ?? {}),
    };

    const fingerprint = JSON.stringify({
      code: upperCode,
      symbol: normalizedSymbol,
      params,
    });

    const isRefresh = fingerprint === lastFingerprintRef.current && result !== null;

    if (isRefresh) {
      setState("refreshing");
    } else {
      setState("loading");
      setError(null);
      setResult(null);
    }

    lastFingerprintRef.current = fingerprint;
    if (symbolFirst) {
      setInputSymbol(normalizedSymbol);
      if (leafId && normalizedSymbol) {
        internalSymbolSync.current = normalizedSymbol;
        setLeafTarget(leafId, upperCode, normalizedSymbol);
      }
    }
    try {
      const res = await runFunction<unknown>(upperCode, {
        symbol: symbolFirst ? normalizedSymbol || undefined : undefined,
        asset_class: runAssetClass,
        params: Object.keys(params).length ? params : undefined,
        signal,
        timeoutMs: functionTimeoutMs(upperCode, entry?.category),
      });
      if (symbolFirst && normalizedSymbol) pushRecentSymbol(normalizedSymbol);
      setResult(res);
      setState("ok");
    } catch (err) {
      // QA-2026-05-23 — abort cleanup. Rapid symbol switches (typing in
      // the symbol box, clicking through quick-symbol chips, or the
      // upstream `upperCode/symbol` effect re-firing) cancel the inflight
      // request via `activeRequest.current?.abort()`. Without resetting
      // state here, the previous `setState("loading")` + the rewritten
      // `lastFingerprintRef` linger and the next render shows a ghost
      // spinner until the new request resolves. Reset both so the next
      // `load` starts from a clean idle slate.
      if (signal?.aborted) {
        setState("idle");
        lastFingerprintRef.current = "";
        return;
      }
      // QA-2026-05-23 — timeout surface. `runFunction` throws a
      // FunctionCallError with body === "timeout" when its internal
      // AbortController fires the 35s timer (default — see
      // functionTimeoutMs above). Surface a dedicated "timeout" state
      // so the result section can render the Turkish "Veri alınamadı"
      // empty state + Retry button instead of an opaque error message.
      const isTimeout =
        err instanceof FunctionCallError &&
        (err.body === "timeout" || err.message.includes("timed out"));
      setError(err instanceof Error ? err.message : String(err));
      setState(isTimeout ? "timeout" : "error");
    }
  };

  const runLatest = (runSymbol = effectiveSymbol) => {
    activeRequest.current?.abort();
    const ac = new AbortController();
    activeRequest.current = ac;
    void load(ac.signal, runSymbol).finally(() => {
      if (activeRequest.current === ac) activeRequest.current = null;
    });
  };

  useEffect(() => {
    const runSymbol =
      compatibleRequestedSymbol(symbol, entry) || (symbolFirst ? defaultRunSymbol : "");
    if (symbolFirst && internalSymbolSync.current === runSymbol) {
      internalSymbolSync.current = null;
      setInputSymbol(runSymbol);
    }
    setInputSymbol(runSymbol);
    activeRequest.current?.abort();
    const ac = new AbortController();
    activeRequest.current = ac;
    const initialQuery = defaultQueryForFunction(upperCode, entry?.category);
    const initialBacktestStrategy = defaultBacktestStrategyForFunction(upperCode);
    const initialControlParams = {
      ...buildControlParams(controlProfile, limit, range, initialQuery),
      ...buildOptionDefaultsForFunction(upperCode),
      ...buildBacktestControlParams(upperCode, initialBacktestStrategy),
      ...(upperCode === "MLSIG" ? { horizon: 1 } : {}),
      ...buildSimpleControlParams(upperCode, defaultSimpleParamsForFunction(upperCode)),
      ...(controlProfile.tradeTicket
        ? {
            side: "BUY",
            quantity: 1,
            type: "MARKET",
            tif: "DAY",
            submit: false,
          }
        : {}),
    };
    setQueryText(initialQuery);
    void load(ac.signal, runSymbol, initialControlParams).finally(() => {
      if (activeRequest.current === ac) activeRequest.current = null;
    });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upperCode, symbol, entry?.category, assetClassKey, symbolFirst, defaultRunSymbol]);

  useEffect(() => {
    if (!controlsReady.current) {
      controlsReady.current = true;
      return;
    }
    if (!controlProfile.limit && !controlProfile.days) return;
    const timer = window.setTimeout(() => {
      runLatest(normalizeSymbolInput(inputSymbol) || effectiveSymbol);
    }, 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, range]);

  useEffect(() => {
    setQueryText(defaultQueryForFunction(upperCode, entry?.category));
  }, [upperCode, entry?.category]);

  useEffect(() => {
    setTicketSide("BUY");
    setTicketQuantity("1");
    setTicketType("MARKET");
    setTicketTif("DAY");
    setBacktestStrategy(defaultBacktestStrategyForFunction(upperCode));
    setMlHorizon("1");
    setSimpleParams(defaultSimpleParamsForFunction(upperCode));
    const optionDefaults = buildOptionDefaultsForFunction(upperCode);
    setOptionSpot(String(optionDefaults.spot ?? 100));
    setOptionStrike(String(optionDefaults.strike ?? 105));
    setOptionShortStrike(String(optionDefaults.short_strike ?? 110));
    setOptionExpiry(String(optionDefaults.years_to_expiry ?? 0.25));
    setOptionVol(String(optionDefaults.vol ?? 0.28));
    setOptionRate(String(optionDefaults.rate ?? 0.045));
    setOptionType(String(optionDefaults.type ?? "CALL") === "PUT" ? "PUT" : "CALL");
    setOptionStrategy(
      String(optionDefaults.strategy ?? "CALL_SPREAD") === "STRADDLE"
        ? "STRADDLE"
        : String(optionDefaults.strategy ?? "CALL_SPREAD") === "LONG_CALL"
          ? "LONG_CALL"
          : "CALL_SPREAD",
    );
  }, [upperCode]);

  // LANG function side-effect: when LANG returns ok with a new lang code,
  // wire it into the UI's i18n.setLocale so <html lang>, the locale
  // catalog, and the LOCALE_CHANGE_EVENT propagate. Without this hook the
  // backend writes runtime/lang.txt but the shell text never changes.
  useEffect(() => {
    if (upperCode !== "LANG" || state !== "ok" || !result) return;
    const data = result.data as { status?: string; lang?: string } | undefined;
    if (!data || (data.status && data.status !== "ok" && data.status !== "ready")) return;
    const next = String(data.lang ?? "").toLowerCase();
    const supported = new Set<Locale>([
      "en", "tr", "de", "fr", "es", "it", "ja", "zh", "ko", "ar", "pt", "ru",
    ]);
    if (next && supported.has(next as Locale)) {
      setLocale(next as Locale);
    }
  }, [upperCode, state, result]);

  const summary = result ? summarizeResult(result.data) : null;
  const payloadStatus = result ? getPayloadStatus(result) : null;

  return (
    <div className="showme-stub-motion u-pane-host--min0" >
      <Pane>
        <PaneHeader
          code={upperCode}
          title={entry?.name ?? upperCode}
          subtitle={entry?.category ?? "function"}
          help={
            <FunctionHelp
              code={upperCode}
              entry={entry}
              symbolFirst={symbolFirst}
              controlProfile={controlProfile}
            />
          }
          trailing={
            <FunctionControlGroup>
              {controlProfile.limit && (
                <RowLimitControl
                  value={limit}
                  onChange={(next) => setLimit(next as RowLimit)}
                  disabled={state === "loading"}
                />
              )}
              {controlProfile.days && (
                <SegmentedControl
                  label="RANGE"
                  value={range}
                  options={STUB_RANGES.map((r) => ({ value: r.id, label: r.label }))}
                  onChange={(next) => setRange(next as StubRangeId)}
                  disabled={state === "loading"}
                />
              )}
              <LoadStatePill state={state} />
              <button
                type="button"
                className="btn btn--accent u-btn-24"
                onClick={() => runLatest()}
                disabled={state === "loading"}
                
              >
                {state === "loading" ? "Running" : "Run"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody style={functionBody}>
          <section className="showme-stub-command showme-card-reveal showme-stub-block" style={commandBar}>
            <div style={functionIdentity}>
              <div style={codeLine}>
                <span className="u-text-accent">{upperCode}</span>
                <span>{entry?.name ?? "ShowMe function"}</span>
              </div>
              <div style={identityMeta}>
                <span>{entry?.category ?? "function"}</span>
                {assetClasses.length ? <span>{assetClasses.join(" / ")}</span> : null}
              </div>
            </div>

            {optionControls ? (
              <OptionAssumptionControls
                code={upperCode}
                spot={optionSpot}
                strike={optionStrike}
                shortStrike={optionShortStrike}
                expiry={optionExpiry}
                vol={optionVol}
                rate={optionRate}
                optionType={optionType}
                strategy={optionStrategy}
                disabled={state === "loading"}
                onSpot={setOptionSpot}
                onStrike={setOptionStrike}
                onShortStrike={setOptionShortStrike}
                onExpiry={setOptionExpiry}
                onVol={setOptionVol}
                onRate={setOptionRate}
                onOptionType={setOptionType}
                onStrategy={setOptionStrategy}
              />
            ) : symbolFirst ? (
              <div style={symbolTools}>
                <Field
                  label="Symbol"
                  value={inputSymbol}
                  onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
                  placeholder={effectiveSymbol || "AAPL, BTCUSDT, EURUSD"}
                  list={`symbol-options-${upperCode}`}
                  hint="Start typing or pick a suggested symbol."
                  trailing={
                    <button
                      type="button"
                      className="btn btn--ghost u-btn-mini"
                      onClick={() => runLatest()}
                      disabled={state === "loading"}
                      
                    >
                      Go
                    </button>
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") runLatest();
                  }}
                />
                <datalist id={`symbol-options-${upperCode}`}>
                  {suggestedSymbolsForFunction(quickSymbols, assetClasses, entry?.category).map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
                <div style={quickRow}>
                  {quickSymbols.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="btn btn--ghost u-btn-mini"
                      onClick={() => {
                        setInputSymbol(s);
                        runLatest(s);
                      }}
                      disabled={state === "loading"}
                      
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : controlProfile.queryParam ? (
              <div style={symbolTools}>
                <Field
                  label={
                    controlProfile.queryLabel ??
                    (controlProfile.queryParam === "topic"
                      ? "Topic"
                      : controlProfile.queryParam === "symbols"
                        ? "Watchlist"
                        : "Query")
                  }
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  placeholder={defaultQueryForFunction(upperCode, entry?.category)}
                  hint={controlProfile.queryHint ?? `${controlProfile.queryParam} sent to backend on Run.`}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") runLatest();
                  }}
                />
              </div>
            ) : (
              <div style={scopeBlock}>
                <span style={metaLabel}>Scope</span>
                <strong>
                  {entry?.category === "portfolio" ? "local portfolio" : "global"}
                </strong>
              </div>
            )}

            {controlProfile.tradeTicket ? (
              <TradeTicketControls
                side={ticketSide}
                quantity={ticketQuantity}
                type={ticketType}
                tif={ticketTif}
                disabled={state === "loading"}
                onSide={setTicketSide}
                onQuantity={setTicketQuantity}
                onType={setTicketType}
                onTif={setTicketTif}
              />
            ) : null}

            {backtestControls ? (
              <BacktestControls
                code={upperCode}
                value={backtestStrategy}
                disabled={state === "loading"}
                onChange={setBacktestStrategy}
              />
            ) : null}

            {mlSignalControls ? (
              <MLSignalControls
                horizon={mlHorizon}
                disabled={state === "loading"}
                onHorizon={setMlHorizon}
              />
            ) : null}

            {simpleControlSpecs.length > 0 ? (
              <SimpleParamControls
                specs={simpleControlSpecs}
                values={simpleParams}
                disabled={state === "loading"}
                onChange={(key, value) => setSimpleParams((prev) => ({ ...prev, [key]: value }))}
              />
            ) : null}

            {controlProfile.transcriptText ? (
              <section style={controlInlinePanel}>
                <span style={metaLabel}>Transcript text</span>
                <textarea
                  value={transcriptText}
                  onChange={(e) => setTranscriptText(e.target.value)}
                  placeholder="Paste earnings-call transcript text here before Run."
                  spellCheck={false}
                  style={{ ...textareaStyle, minHeight: 86 }}
                />
              </section>
            ) : null}

            <div style={commandActions}>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setParamsText(mergeParams(paramsText, { deep: true }));
                  setAdvancedOpen(true);
                }}
                disabled={state === "loading"}
              >
                Deep
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setAdvancedOpen((open) => !open)}
                disabled={state === "loading"}
              >
                {advancedOpen ? "Hide JSON" : "Advanced"}
              </button>
            </div>
          </section>

          {advancedOpen ? (
            <section className="showme-stub-advanced showme-card-reveal showme-stub-block" style={advancedPanel}>
              <div style={advancedHeader}>
                <div>
                  <strong className="u-text-primary">Params JSON</strong>
                  <span style={{ color: "var(--text-mute)", marginLeft: 8 }}>
                    {paramsText.trim() ? "custom override" : "default payload"}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setParamsText("")}
                  disabled={state === "loading" || !paramsText.trim()}
                >
                  Clear
                </button>
              </div>
              <textarea
                value={paramsText}
                onChange={(e) => setParamsText(e.target.value)}
                placeholder={paramsPlaceholder(upperCode)}
                spellCheck={false}
                style={textareaStyle}
              />
            </section>
          ) : null}

          <section className="showme-stub-result" style={resultPane}>
            {state === "loading" ? (
              <div className="showme-card-reveal showme-stub-block u-grid-gap-10">
                <Skeleton height={24} width="38%" />
                <Skeleton height={260} />
                <Skeleton height={16} width="70%" />
                <Skeleton height={16} width="54%" />
              </div>
            ) : state === "timeout" && !result ? (
              <Empty
                title="Veri alınamadı — yeniden dene"
                body={
                  error
                    ? `${error} · 35 saniye içinde yanıt alınamadı.`
                    : "Sidecar 35 saniye içinde yanıt vermedi. Bağlantınızı veya backend durumunu kontrol edin."
                }
                icon="!"
                action={
                  <button
                    type="button"
                    className="btn btn--accent"
                    data-testid="function-stub-timeout"
                    onClick={() => runLatest()}
                  >
                    Yeniden dene
                  </button>
                }
              />
            ) : state === "error" && !result ? (
              <Empty
                title="Function failed"
                body={error ?? "Unknown sidecar error"}
                icon="!"
                action={
                  <button type="button" className="btn btn--accent" onClick={() => runLatest()}>
                    Retry
                  </button>
                }
              />
            ) : result && summary && payloadStatus ? (
              <GenericResult
                result={result}
                summary={summary}
                payloadStatus={payloadStatus}
                onRetry={() => runLatest()}
              />
            ) : (
              <Empty title="No result yet" body="Run this function to fetch a live payload." />
            )}
          </section>
        </PaneBody>
        <PaneFooter>
          <span>{entry?.category ?? "unknown"}</span>
          <span>code · {upperCode}</span>
          <span>transport · /api/fn/{upperCode}</span>
          {symbolFirst && effectiveSymbol && <span>symbol · {effectiveSymbol}</span>}
          {controlProfile.limit && <span>rows · {limit}</span>}
          {controlProfile.days && <span>range · {range}</span>}
        </PaneFooter>
      </Pane>
    </div>
  );
}

export default FunctionStub;
