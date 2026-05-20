import { Field } from "@/design-system";
import { SegmentedControl } from "@/functions/function-controls";
import type {
  BacktestStrategy,
  MLHorizon,
  OptionStrategy,
  OptionType,
  SimpleParamSpec,
  TicketSide,
  TicketTif,
  TicketType,
} from "./_types";
import {
  controlInlinePanel,
  optionStrategyControl,
  ticketControls,
} from "./styles";

export function TradeTicketControls({
  side,
  quantity,
  type,
  tif,
  disabled,
  onSide,
  onQuantity,
  onType,
  onTif,
}: {
  side: TicketSide;
  quantity: string;
  type: TicketType;
  tif: TicketTif;
  disabled: boolean;
  onSide: (next: TicketSide) => void;
  onQuantity: (next: string) => void;
  onType: (next: TicketType) => void;
  onTif: (next: TicketTif) => void;
}) {
  return (
    <div style={ticketControls}>
      <SegmentedControl
        label="SIDE"
        value={side}
        options={[
          { value: "BUY", label: "BUY" },
          { value: "SELL", label: "SELL" },
        ]}
        onChange={(next) => onSide(next as TicketSide)}
        disabled={disabled}
      />
      <Field
        label="Qty"
        value={quantity}
        type="number"
        min="0"
        step="any"
        inputMode="decimal"
        onChange={(e) => onQuantity(e.target.value)}
        hint="Positive quantity required."
        disabled={disabled}
      />
      <SegmentedControl
        label="TYPE"
        value={type}
        options={[
          { value: "MARKET", label: "Market" },
          { value: "LIMIT", label: "Limit" },
          { value: "STOP", label: "Stop" },
          { value: "STOP_LIMIT", label: "Stop limit" },
        ]}
        onChange={(next) => onType(next as TicketType)}
        disabled={disabled}
      />
      <SegmentedControl
        label="TIF"
        value={tif}
        options={[
          { value: "DAY", label: "Day" },
          { value: "GTC", label: "GTC" },
          { value: "IOC", label: "IOC" },
          { value: "FOK", label: "FOK" },
        ]}
        onChange={(next) => onTif(next as TicketTif)}
        disabled={disabled}
      />
    </div>
  );
}

export function BacktestControls({
  code,
  value,
  disabled,
  onChange,
}: {
  code: string;
  value: BacktestStrategy;
  disabled: boolean;
  onChange: (next: BacktestStrategy) => void;
}) {
  const isMatrix = code === "BMTX";
  const current = isMatrix ? value : value === "ALL" ? "sma_crossover" : value;
  const options = [
    ...(isMatrix ? [{ value: "ALL" as const, label: "All" }] : []),
    { value: "sma_crossover" as const, label: "SMA" },
    { value: "rsi_meanrev" as const, label: "RSI" },
    { value: "buy_and_hold" as const, label: "Buy/hold" },
  ];
  return (
    <section style={controlInlinePanel}>
      <SegmentedControl
        label="STRATEGY"
        value={current}
        options={options}
        onChange={(next) => onChange(next as BacktestStrategy)}
        disabled={disabled}
        title="Backtest strategy"
      />
    </section>
  );
}

export function MLSignalControls({
  horizon,
  disabled,
  onHorizon,
}: {
  horizon: MLHorizon;
  disabled: boolean;
  onHorizon: (next: MLHorizon) => void;
}) {
  return (
    <section style={controlInlinePanel}>
      <SegmentedControl
        label="HORIZON"
        value={horizon}
        options={[
          { value: "1", label: "1D" },
          { value: "5", label: "5D" },
          { value: "20", label: "20D" },
        ]}
        onChange={(next) => onHorizon(next as MLHorizon)}
        disabled={disabled}
        title="Prediction horizon"
      />
    </section>
  );
}

export function SimpleParamControls({
  specs,
  values,
  disabled,
  onChange,
}: {
  specs: SimpleParamSpec[];
  values: Record<string, string>;
  disabled: boolean;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <section style={ticketControls}>
      {specs.map((spec) => (
        <Field
          key={spec.key}
          label={spec.label}
          value={values[spec.key] ?? ""}
          onChange={(e) => onChange(spec.key, e.target.value)}
          placeholder={spec.hint}
          hint={spec.hint}
          disabled={disabled}
        />
      ))}
    </section>
  );
}

export function OptionAssumptionControls({
  code,
  spot,
  strike,
  shortStrike,
  expiry,
  vol,
  rate,
  optionType,
  strategy,
  disabled,
  onSpot,
  onStrike,
  onShortStrike,
  onExpiry,
  onVol,
  onRate,
  onOptionType,
  onStrategy,
}: {
  code: string;
  spot: string;
  strike: string;
  shortStrike: string;
  expiry: string;
  vol: string;
  rate: string;
  optionType: OptionType;
  strategy: OptionStrategy;
  disabled: boolean;
  onSpot: (next: string) => void;
  onStrike: (next: string) => void;
  onShortStrike: (next: string) => void;
  onExpiry: (next: string) => void;
  onVol: (next: string) => void;
  onRate: (next: string) => void;
  onOptionType: (next: OptionType) => void;
  onStrategy: (next: OptionStrategy) => void;
}) {
  const isStrategy = code === "OSA";
  return (
    <section style={controlInlinePanel}>
      <div style={ticketControls}>
        {isStrategy ? (
          <div style={optionStrategyControl}>
            <SegmentedControl
              label="STRATEGY"
              value={strategy}
              options={[
                { value: "CALL_SPREAD", label: "Call spread" },
                { value: "LONG_CALL", label: "Long call" },
                { value: "STRADDLE", label: "Straddle" },
              ]}
              onChange={(next) => onStrategy(next as OptionStrategy)}
              disabled={disabled}
            />
          </div>
        ) : (
          <SegmentedControl
            label="TYPE"
            value={optionType}
            options={[
              { value: "CALL", label: "Call" },
              { value: "PUT", label: "Put" },
            ]}
            onChange={(next) => onOptionType(next as OptionType)}
            disabled={disabled}
          />
        )}
        <Field
          label="Spot"
          value={spot}
          type="number"
          step="any"
          inputMode="decimal"
          onChange={(e) => onSpot(e.target.value)}
          disabled={disabled}
        />
        <Field
          label={isStrategy ? "Long K" : "Strike"}
          value={strike}
          type="number"
          step="any"
          inputMode="decimal"
          onChange={(e) => onStrike(e.target.value)}
          disabled={disabled}
        />
        {isStrategy ? (
          <Field
            label="Short K"
            value={shortStrike}
            type="number"
            step="any"
            inputMode="decimal"
            onChange={(e) => onShortStrike(e.target.value)}
            disabled={disabled || strategy !== "CALL_SPREAD"}
          />
        ) : null}
        <Field
          label="T years"
          value={expiry}
          type="number"
          min="0"
          step="0.01"
          inputMode="decimal"
          onChange={(e) => onExpiry(e.target.value)}
          disabled={disabled}
        />
        <Field
          label="Vol"
          value={vol}
          type="number"
          min="0"
          step="0.01"
          inputMode="decimal"
          onChange={(e) => onVol(e.target.value)}
          disabled={disabled}
        />
        <Field
          label="Rate"
          value={rate}
          type="number"
          step="0.001"
          inputMode="decimal"
          onChange={(e) => onRate(e.target.value)}
          disabled={disabled}
        />
      </div>
    </section>
  );
}
