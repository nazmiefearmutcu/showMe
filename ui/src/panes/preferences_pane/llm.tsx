import { useEffect, useState } from "react";
import { Card, CardBody, CardHeader, Pill } from "@/design-system";
import { useAppStore } from "@/lib/store";
import { sidecarFetch } from "@/lib/sidecar";
import type { LlmCost } from "./_types";
import { SummaryStat } from "./migration";

export function LlmSection() {
  const port = useAppStore((s) => s.sidecarPort);
  const [data, setData] = useState<LlmCost | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!port) return;
    let cancelled = false;
    setError(null);
    // 2026-05-11 hotfix: route through sidecarFetch so the auth token gets
    // attached automatically — bypassing it would 401 against the live
    // signed build's auth middleware.
    sidecarFetch<LlmCost>("/api/llm/cost")
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [port, tick]);

  return (
    <Card>
      <CardHeader
        trailing={
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setTick((t) => t + 1)}
          >
            ⟳
          </button>
        }
      >
        LLM planner cost ledger
      </CardHeader>
      <CardBody>
        <p className="about-llm-desc">
          Planner providers are used only when their keys are configured.
          Today's spend is capped at{" "}
          <code>${data?.cap_usd?.toFixed(2) ?? "1.00"}</code> — override via the{" "}
          <code>SHOWME_LLM_DAILY_USD</code> env var.
        </p>

        {error && <div className="about-llm-error">{error}</div>}

        {data && (
          <>
            <div className="about-llm-stat-grid">
              <SummaryStat
                label="today $"
                value={`$${data.today_usd.toFixed(4)}`}
              />
              <SummaryStat
                label="remaining"
                value={`$${data.remaining_usd.toFixed(4)}`}
              />
              <SummaryStat label="cap" value={`$${data.cap_usd.toFixed(2)}`} />
              <SummaryStat label="entries" value={data.entries.length} />
              <SummaryStat
                label="state"
                value={data.exhausted ? "capped" : "open"}
              />
              <SummaryStat
                label="providers"
                value={data.providers.length || "fallback only"}
              />
            </div>
            <div className="u-mt-12">
              <div className="about-llm-section-head">Configured providers</div>
              <div className="u-flex u-gap-6 u-flex-wrap">
                {data.providers.length === 0 ? (
                  <span className="u-text-11 u-text-mute">
                    No API keys configured — deterministic planner only.
                  </span>
                ) : (
                  data.providers.map((p) => (
                    <Pill key={p.name} tone="accent" withDot={false}>
                      {p.name} · {p.model}
                    </Pill>
                  ))
                )}
              </div>
            </div>
            {data.entries.length > 0 && (
              <div className="u-mt-12">
                <div className="about-llm-section-head">
                  Recent calls (last 50)
                </div>
                <div className="about-llm-calls">
                  {data.entries
                    .slice()
                    .reverse()
                    .map((e, i) => (
                      <div
                        key={i}
                        className={`about-llm-call${i === data.entries.length - 1 ? " about-llm-call--last" : ""}`}
                      >
                        <span>{e.ts.slice(0, 19).replace("T", " ")}</span>
                        <span className="u-text-accent">
                          {e.provider} · {e.model}
                        </span>
                        <span>{e.input_tokens}↓</span>
                        <span>{e.output_tokens}↑</span>
                        <span
                          className={
                            e.usd >= 0.01 ? "u-text-warn" : "u-text-primary"
                          }
                        >
                          ${e.usd.toFixed(5)}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
