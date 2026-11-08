/**
 * IPO — IPO calendar (Awareness-backed).
 *
 * Rows come from awareness `/calendar/corporate` (type ipo), bucketed by the
 * backend into priced / upcoming / filed / withdrawn. The status control filters
 * client-side. Sections always render in the order Upcoming, Priced, Filed,
 * Withdrawn.
 *
 * Awareness carries no quotes, so the pane shows no first-day performance.
 */
import { useMemo } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { formatMissing } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import { AwarenessUnavailable } from "./awareness/AwarenessUnavailable";
import { ProviderHealthStrip } from "./awareness/ProviderHealthStrip";
import type { AwarenessMeta } from "./awareness/types";
import type { ProvenanceSource } from "./awareness/ProvenanceButton";
import { ProvenanceButton } from "./awareness/ProvenanceButton";

export interface IpoRow {
  date?: string | null;
  symbol?: string | null;
  company?: string | null;
  exchange?: string | null;
  price?: number | string | null;
  price_range?: string | [number, number] | null;
  shares_offered?: number | null;
  deal_size_usd?: number | null;
  status?: string | null;
  sources?: ProvenanceSource[] | null;
}

type SectionKey = "upcoming" | "priced" | "filed" | "withdrawn";

interface IpoPayload {
  status?: string;
  reason?: string | null;
  sections?: Partial<Record<SectionKey, IpoRow[]>>;
  meta?: AwarenessMeta;
}

const SECTION_ORDER: SectionKey[] = ["upcoming", "priced", "filed", "withdrawn"];
const SECTION_LABEL: Record<SectionKey, string> = {
  upcoming: "Upcoming",
  priced: "Priced",
  filed: "Filed",
  withdrawn: "Withdrawn",
};

const FILTERS = [
  { value: "all", label: "All" },
  { value: "upcoming", label: "Upcoming" },
  { value: "priced", label: "Priced" },
  { value: "filed", label: "Filed" },
  { value: "withdrawn", label: "Withdrawn" },
] as const;
type FilterId = (typeof FILTERS)[number]["value"];
const FILTER_IDS = FILTERS.map((o) => o.value);

export function IPOPane({ code }: FunctionPaneProps) {
  const [filter, setFilter] = usePersistentOption<FilterId>(
    "showme.ipo.filter",
    FILTER_IDS,
    "all",
  );
  const params = useMemo(() => ({ days_back: 30, days_ahead: 60 }), []);
  const { state, data, error, refetch } = useFunction<IpoPayload>({ code, params });
  const payload: IpoPayload = data?.data ?? {};
  const status = payload.status ?? "—";
  const unavailable = status === "provider_unavailable";
  const meta: AwarenessMeta = payload.meta ?? {};

  const sections = useMemo(() => {
    const out: Record<SectionKey, IpoRow[]> = {
      upcoming: [],
      priced: [],
      filed: [],
      withdrawn: [],
    };
    for (const key of SECTION_ORDER) out[key] = payload.sections?.[key] ?? [];
    return out;
  }, [payload.sections]);
  const total = SECTION_ORDER.reduce((n, k) => n + sections[k].length, 0);
  const counts: Record<FilterId, number> = {
    all: total,
    upcoming: sections.upcoming.length,
    priced: sections.priced.length,
    filed: sections.filed.length,
    withdrawn: sections.withdrawn.length,
  };
  const visibleKeys =
    filter === "all" ? SECTION_ORDER : SECTION_ORDER.filter((k) => k === filter);
  const filterOptions = FILTERS.map((o) => ({
    value: o.value,
    label: `${o.label} ${counts[o.value]}`,
  }));

  const body = (() => {
    if (state === "loading" || state === "idle") {
      return (
        <div className="u-grid-gap-8">
          <Skeleton height={20} />
          <Skeleton height={20} />
          <Skeleton height={20} width="80%" />
        </div>
      );
    }
    if (state === "error") {
      return (
        <Empty
          title="Function error"
          body={error?.message ?? formatMissing}
          icon="!"
          action={
            <button type="button" className="btn" onClick={refetch}>
              Retry
            </button>
          }
        />
      );
    }
    if (unavailable) {
      return (
        <AwarenessUnavailable
          reason={payload.reason ?? null}
          onRetry={refetch}
          subject="IPO calendar"
        />
      );
    }
    if (total === 0) {
      return (
        <Empty
          title="No IPO activity in this window"
          body="No priced, upcoming, filed or withdrawn offerings in the last 30 days or next 60 days. Nothing is estimated."
        />
      );
    }
    return (
      <div className="aw-ipo">
        {visibleKeys.map((key) => (
          <IpoSection key={key} sectionKey={key} rows={sections[key]} />
        ))}
        <p className="aw-cal__legend">
          Awareness carries no quotes, so no first-day performance is shown. Price shows the
          offer price when priced, otherwise the marketed range; n/a when neither is
          reported. Shares in millions, deal size in USD.
        </p>
      </div>
    );
  })();

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="IPO calendar"
          subtitle={`${total} offerings · last 30 days to next 60`}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh the IPO calendar"
              />
            </FunctionControlGroup>
          }
        />
        <div className="aw-cal__toolbar" role="toolbar" aria-label="IPO status filter">
          <SegmentedControl
            label="STATUS"
            title="IPO status"
            value={filter}
            options={filterOptions}
            onChange={setFilter}
          />
        </div>
        <ProviderHealthStrip
          providers={meta.providers}
          feedHealth={meta.feed_health}
          generatedAt={meta.generated_at}
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "awareness"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="offerings" value={total} />
          <StatusDivider />
          <StatusSection label="filter" value={filter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function IpoSection({ sectionKey, rows }: { sectionKey: SectionKey; rows: IpoRow[] }) {
  const label = SECTION_LABEL[sectionKey];
  return (
    <section className="aw-ipo__section" aria-label={`${label} IPOs`}>
      <header className="aw-ipo__sechead">
        <span className="aw-ipo__secname">{label}</span>
        <span className="aw-ipo__secmeta">{rows.length} offerings</span>
      </header>
      {rows.length === 0 ? (
        <div className="aw-ipo__none">None in this window.</div>
      ) : (
        <div className="aw-ipo__grid" role="table" aria-label={`${label} IPO rows`}>
          <div className="aw-ipo__head" role="row">
            <span role="columnheader">Date</span>
            <span role="columnheader">Symbol</span>
            <span role="columnheader">Company</span>
            <span role="columnheader">Exchange</span>
            <span role="columnheader" className="aw-num">
              Price / range
            </span>
            <span role="columnheader" className="aw-num">
              Shares
            </span>
            <span role="columnheader" className="aw-num">
              Deal size
            </span>
            <span role="columnheader">Status</span>
            <span role="columnheader">Src</span>
          </div>
          {rows.map((r, i) => (
            <div
              key={`${r.symbol ?? ""}-${i}`}
              className={`aw-ipo__row${sectionKey === "withdrawn" ? " aw-ipo__row--withdrawn" : ""}`}
              role="row"
            >
              <span role="cell" className="aw-num">
                {fmtDay(r.date)}
              </span>
              <span role="cell" className="aw-ipo__symbol">
                {r.symbol ?? formatMissing}
              </span>
              <span role="cell" className="aw-ipo__company">
                {r.company ?? formatMissing}
              </span>
              <span role="cell">{r.exchange ?? formatMissing}</span>
              <span role="cell" className="aw-num">
                {priceText(r, sectionKey)}
              </span>
              <span role="cell" className="aw-num">
                {fmtShares(r.shares_offered)}
              </span>
              <span role="cell" className="aw-num">
                {fmtDeal(r.deal_size_usd)}
              </span>
              <span role="cell">
                <span className={`aw-ipo__status aw-ipo__status--${sectionKey}`}>
                  {SECTION_LABEL[sectionKey].toLowerCase()}
                </span>
              </span>
              <span role="cell">
                <ProvenanceButton sources={r.sources} subject={r.symbol ?? "IPO"} />
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function priceText(r: IpoRow, key: SectionKey): string {
  if (key === "priced" && r.price != null && r.price !== "") {
    return typeof r.price === "number" ? `$${r.price.toFixed(2)}` : String(r.price);
  }
  if (r.price_range) {
    if (Array.isArray(r.price_range)) {
      const [lo, hi] = r.price_range;
      return `$${lo.toFixed(2)}–${hi.toFixed(2)}`;
    }
    return String(r.price_range);
  }
  if (r.price != null && r.price !== "") {
    return typeof r.price === "number" ? `$${r.price.toFixed(2)}` : String(r.price);
  }
  return "n/a";
}

function fmtShares(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return formatMissing;
  return `${(v / 1e6).toFixed(1)}M`;
}

function fmtDeal(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return formatMissing;
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  return `$${(v / 1e6).toFixed(0)}M`;
}

function fmtDay(v: string | null | undefined): string {
  if (!v) return formatMissing;
  const d = new Date(`${String(v).slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return formatMissing;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
