import type { CSSProperties, ReactNode } from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const accent = "#d98a3d";
const green = "#31c48d";
const ink = "#f4efe4";
const muted = "#a99d86";
const easing = Easing.bezier(0.16, 1, 0.3, 1);

const seconds = (value: number, fps: number) => Math.round(value * fps);

const ease = (
  frame: number,
  input: [number, number],
  output: [number, number],
) =>
  interpolate(frame, input, output, {
    easing,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

const linear = (
  frame: number,
  input: [number, number],
  output: [number, number],
) =>
  interpolate(frame, input, output, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

const sceneOpacity = (frame: number, duration: number, fps: number) => {
  const fade = seconds(0.55, fps);
  return Math.min(
    linear(frame, [0, fade], [0, 1]),
    linear(frame, [duration - fade, duration], [1, 0]),
  );
};

const baseFont: CSSProperties = {
  fontFamily:
    'Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif',
  color: ink,
};

const monoFont: CSSProperties = {
  fontFamily:
    '"SF Mono", "Roboto Mono", Menlo, Monaco, Consolas, monospace',
  letterSpacing: 0,
};

const asset = (name: string) => staticFile(`assets/${name}`);

const AmbientGrid = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const drift = linear(frame % seconds(8, fps), [0, seconds(8, fps)], [0, 64]);

  return (
    <AbsoluteFill
      style={{
        background:
          "radial-gradient(circle at 15% 20%, rgba(217,138,61,0.20), transparent 30%), radial-gradient(circle at 85% 18%, rgba(49,196,141,0.14), transparent 28%), linear-gradient(135deg, #090a0c 0%, #121111 48%, #18130d 100%)",
      }}
    >
      <AbsoluteFill
        style={{
          opacity: 0.18,
          backgroundImage:
            "linear-gradient(rgba(244,239,228,0.18) 1px, transparent 1px), linear-gradient(90deg, rgba(244,239,228,0.18) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          transform: `translate(${drift}px, ${drift * 0.45}px)`,
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(90deg, rgba(9,10,12,0.92) 0%, rgba(9,10,12,0.52) 42%, rgba(9,10,12,0.90) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};

const Eyebrow = ({ children, color = accent }: { children: ReactNode; color?: string }) => (
  <div
    style={{
      ...monoFont,
      color,
      fontSize: 24,
      fontWeight: 800,
    }}
  >
    {children}
  </div>
);

const Metric = ({
  value,
  label,
  delay,
}: {
  value: string;
  label: string;
  delay: number;
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const appear = ease(frame, [delay, delay + seconds(0.7, fps)], [0, 1]);

  return (
    <div
      style={{
        width: 256,
        padding: "22px 24px",
        border: "1px solid rgba(244,239,228,0.16)",
        borderRadius: 8,
        background: "rgba(18,18,18,0.82)",
        transform: `translateY(${(1 - appear) * 28}px)`,
        opacity: appear,
      }}
    >
      <div style={{ ...monoFont, color: ink, fontSize: 40, fontWeight: 900 }}>
        {value}
      </div>
      <div
        style={{
          color: muted,
          fontSize: 18,
          marginTop: 8,
          lineHeight: 1.25,
          fontWeight: 700,
        }}
      >
        {label}
      </div>
    </div>
  );
};

const CodeChip = ({ children, active = false }: { children: ReactNode; active?: boolean }) => (
  <div
    style={{
      ...monoFont,
      height: 48,
      minWidth: 92,
      padding: "0 18px",
      borderRadius: 6,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: active ? "#111" : ink,
      background: active ? accent : "rgba(244,239,228,0.09)",
      border: `1px solid ${active ? accent : "rgba(244,239,228,0.16)"}`,
      fontSize: 22,
      fontWeight: 900,
    }}
  >
    {children}
  </div>
);

const MockWindow = ({
  title,
  children,
  style,
}: {
  title: string;
  children: ReactNode;
  style?: CSSProperties;
}) => (
  <div
    style={{
      position: "absolute",
      overflow: "hidden",
      borderRadius: 8,
      background: "#f3ecd9",
      color: "#21190e",
      border: "1px solid rgba(244,239,228,0.28)",
      boxShadow: "0 34px 90px rgba(0,0,0,0.48)",
      ...style,
    }}
  >
    <div
      style={{
        height: 42,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 16px",
        background: "#e9dec5",
        borderBottom: "1px solid rgba(93,72,42,0.22)",
      }}
    >
      <div style={{ width: 12, height: 12, borderRadius: 99, background: "#ff5f57" }} />
      <div style={{ width: 12, height: 12, borderRadius: 99, background: "#febc2e" }} />
      <div style={{ width: 12, height: 12, borderRadius: 99, background: "#28c840" }} />
      <div style={{ ...monoFont, marginLeft: 10, fontSize: 14, fontWeight: 900 }}>
        {title}
      </div>
      <div
        style={{
          ...monoFont,
          marginLeft: "auto",
          color: "#1f7a53",
          fontSize: 13,
          fontWeight: 900,
        }}
      >
        healthy
      </div>
    </div>
    {children}
  </div>
);

const SideItem = ({ label, active = false }: { label: string; active?: boolean }) => (
  <div
    style={{
      ...monoFont,
      height: 26,
      display: "flex",
      alignItems: "center",
      padding: "0 10px",
      borderRadius: 4,
      color: active ? "#241407" : "#6d604c",
      background: active ? "#d9c69d" : "transparent",
      fontSize: 12,
      fontWeight: 850,
    }}
  >
    {label}
  </div>
);

const MiniBar = ({ value, color = green }: { value: number; color?: string }) => (
  <div style={{ height: 7, borderRadius: 99, background: "rgba(33,25,14,0.12)" }}>
    <div
      style={{
        width: `${value}%`,
        height: "100%",
        borderRadius: 99,
        background: color,
      }}
    />
  </div>
);

const CockpitMock = ({ style }: { style?: CSSProperties }) => {
  const kpis = [
    ["SPX", "7,557.21", "+1.67%"],
    ["NDX", "30,196.83", "+3.07%"],
    ["BTC", "72,918.03", "-3.37%"],
    ["DXY", "99.01", "-0.31%"],
    ["VIX", "15.99", "-4.25%"],
  ];

  return (
    <MockWindow title="ShowMe Cockpit" style={style}>
      <div
        style={{
          height: "calc(100% - 42px)",
          display: "grid",
          gridTemplateColumns: "164px 1fr 260px",
          gap: 12,
          padding: 14,
          background:
            "linear-gradient(rgba(136,111,70,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(136,111,70,0.08) 1px, transparent 1px), #f6efd9",
          backgroundSize: "24px 24px",
        }}
      >
        <div style={{ borderRight: "1px solid rgba(93,72,42,0.18)", paddingRight: 10 }}>
          <SideItem label="Overview" active />
          <SideItem label="Watchlist" />
          <SideItem label="Portfolio" />
          <SideItem label="News Desk" />
          <SideItem label="All Functions" />
          <SideItem label="Multi-Indicator Scan" />
          <SideItem label="Strategy Editor" />
          <SideItem label="Bot Supervision" />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
            {kpis.map(([name, value, change]) => (
              <div
                key={name}
                style={{
                  background: "rgba(255,255,255,0.44)",
                  border: "1px solid rgba(93,72,42,0.18)",
                  padding: 10,
                  minHeight: 72,
                }}
              >
                <div style={{ ...monoFont, fontSize: 11, fontWeight: 900 }}>{name}</div>
                <div style={{ ...monoFont, fontSize: 18, fontWeight: 950, marginTop: 5 }}>
                  {value}
                </div>
                <div
                  style={{
                    ...monoFont,
                    color: change.startsWith("+") ? "#168759" : "#c34c5d",
                    fontSize: 12,
                    fontWeight: 950,
                    marginTop: 4,
                  }}
                >
                  {change}
                </div>
              </div>
            ))}
          </div>
          <div
            style={{
              background: "rgba(255,255,255,0.52)",
              border: "1px solid rgba(93,72,42,0.18)",
              padding: 14,
            }}
          >
            <div style={{ ...monoFont, color: "#8a5a24", fontSize: 12, fontWeight: 950 }}>
              Today&apos;s Brief
            </div>
            <div style={{ fontSize: 17, fontWeight: 850, marginTop: 8 }}>
              Inflation cools, liquidity improves, and risk appetite rotates across
              equities and crypto.
            </div>
          </div>
          <div
            style={{
              background: "rgba(255,255,255,0.42)",
              border: "1px solid rgba(93,72,42,0.18)",
              padding: 12,
              flex: 1,
            }}
          >
            <div style={{ ...monoFont, fontSize: 12, fontWeight: 950, marginBottom: 8 }}>
              Live Watchlist
            </div>
            {[
              ["AAPL", "311.82", "+3.17%", 74],
              ["MSFT", "424.35", "+0.78%", 58],
              ["GOOGL", "390.14", "+0.32%", 52],
              ["BTCUSDT", "72,918", "-3.37%", 44],
              ["ETHUSDT", "1,990", "-4.20%", 36],
            ].map(([symbol, price, change, bar]) => (
              <div
                key={symbol}
                style={{
                  display: "grid",
                  gridTemplateColumns: "90px 1fr 90px 130px",
                  gap: 10,
                  alignItems: "center",
                  height: 31,
                  borderTop: "1px solid rgba(93,72,42,0.11)",
                  ...monoFont,
                  fontSize: 12,
                  fontWeight: 850,
                }}
              >
                <div>{symbol}</div>
                <div>{price}</div>
                <div style={{ color: String(change).startsWith("+") ? "#168759" : "#c34c5d" }}>
                  {change}
                </div>
                <MiniBar value={Number(bar)} color={String(change).startsWith("+") ? green : "#c34c5d"} />
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div
            style={{
              border: "1px solid rgba(93,72,42,0.18)",
              background: "rgba(255,255,255,0.42)",
              padding: 14,
              minHeight: 126,
            }}
          >
            <div style={{ ...monoFont, color: "#1f7a53", fontSize: 12, fontWeight: 950 }}>
              Sentiment / 24h
            </div>
            <div style={{ fontSize: 34, fontWeight: 950, marginTop: 18 }}>Neutral</div>
            <MiniBar value={50} />
          </div>
          <div
            style={{
              border: "1px solid rgba(93,72,42,0.18)",
              background: "rgba(255,255,255,0.42)",
              padding: 14,
              flex: 1,
            }}
          >
            <div style={{ ...monoFont, fontSize: 12, fontWeight: 950, marginBottom: 10 }}>
              Quick Functions
            </div>
            {["OMON", "GEX", "DES", "PORT", "WATCH", "SCAN"].map((code) => (
              <div
                key={code}
                style={{
                  ...monoFont,
                  display: "inline-flex",
                  width: "48%",
                  margin: "0 2% 8px 0",
                  padding: "10px 9px",
                  border: "1px solid rgba(93,72,42,0.18)",
                  fontSize: 12,
                  fontWeight: 950,
                }}
              >
                {code}
              </div>
            ))}
          </div>
        </div>
      </div>
    </MockWindow>
  );
};

const ScanMock = ({ style }: { style?: CSSProperties }) => {
  const markets = ["Crypto", "Equities", "ETFs", "FX", "Commodities", "Bonds"];
  const rows = [
    ["BTCUSDT", "BUY", "91%"],
    ["AAPL", "BUY", "84%"],
    ["GLD", "HOLD", "72%"],
    ["EURUSD", "SELL", "68%"],
  ];

  return (
    <MockWindow title="Multi-Indicator Scan" style={style}>
      <div style={{ height: "calc(100% - 42px)", padding: 18, background: "#f6efd9" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ ...monoFont, color: "#8a5a24", fontSize: 14, fontWeight: 950 }}>
              Market Filters
            </div>
            <div style={{ fontSize: 22, fontWeight: 950, marginTop: 6 }}>
              2/6 markets | Top 50 | 12 timeframes
            </div>
          </div>
          <div
            style={{
              ...monoFont,
              padding: "10px 16px",
              borderRadius: 5,
              background: "#8a5a24",
              color: "#fff5de",
              fontSize: 14,
              fontWeight: 950,
            }}
          >
            Scan
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginTop: 18 }}>
          {markets.map((market, index) => (
            <div
              key={market}
              style={{
                border: `1px solid ${index < 2 ? "#b0793b" : "rgba(93,72,42,0.16)"}`,
                background: index < 2 ? "rgba(217,138,61,0.13)" : "rgba(255,255,255,0.35)",
                padding: 13,
                minHeight: 86,
              }}
            >
              <div style={{ ...monoFont, fontSize: 14, fontWeight: 950 }}>{market}</div>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 10 }}>
                {["1m", "5m", "15m", "1h", "4h", "1d"].map((tf) => (
                  <div
                    key={tf}
                    style={{
                      ...monoFont,
                      border: "1px solid rgba(93,72,42,0.2)",
                      borderRadius: 4,
                      padding: "4px 7px",
                      fontSize: 10,
                      fontWeight: 850,
                    }}
                  >
                    {tf}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 18 }}>
          {["Top Consensus", "Watch Next"].map((title, group) => (
            <div
              key={title}
              style={{
                border: "1px solid rgba(93,72,42,0.18)",
                background: "rgba(255,255,255,0.46)",
                padding: 14,
              }}
            >
              <div style={{ ...monoFont, fontSize: 13, fontWeight: 950, marginBottom: 8 }}>
                {title}
              </div>
              {rows.map(([symbol, signal, score], index) => (
                <div
                  key={`${title}-${symbol}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "90px 70px 1fr",
                    alignItems: "center",
                    gap: 12,
                    height: 34,
                    ...monoFont,
                    fontSize: 12,
                    fontWeight: 850,
                  }}
                >
                  <div>{symbol}</div>
                  <div style={{ color: signal === "SELL" ? "#c34c5d" : "#168759" }}>{signal}</div>
                  <MiniBar value={group === 0 ? 84 - index * 8 : 72 - index * 6} />
                  <div style={{ display: "none" }}>{score}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </MockWindow>
  );
};

const PaletteMock = ({ style }: { style?: CSSProperties }) => (
  <MockWindow title="Command Palette" style={style}>
    <div style={{ height: "calc(100% - 42px)", padding: 18, background: "#f6efd9" }}>
      <div
        style={{
          ...monoFont,
          height: 38,
          display: "flex",
          alignItems: "center",
          padding: "0 14px",
          border: "1px solid rgba(93,72,42,0.22)",
          background: "#fff8e8",
          fontSize: 13,
          fontWeight: 850,
          color: "#6d604c",
        }}
      >
        Type a function: OMON, GEX, DES, PORT, BOT
      </div>
      <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {[
          ["OMON", "Option monitor"],
          ["GEX", "Gamma exposure"],
          ["DES", "Company description"],
          ["PORT", "Portfolio analytics"],
          ["WATCH", "Live watchlist"],
          ["BOT", "Bot manager"],
          ["NI", "News intelligence"],
          ["BTMM", "Rates environment"],
        ].map(([code, label]) => (
          <div
            key={code}
            style={{
              border: "1px solid rgba(93,72,42,0.17)",
              background: "rgba(255,255,255,0.48)",
              padding: 12,
            }}
          >
            <div style={{ ...monoFont, color: "#8a5a24", fontSize: 13, fontWeight: 950 }}>
              {code}
            </div>
            <div style={{ fontSize: 16, fontWeight: 800, marginTop: 4 }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  </MockWindow>
);

const AnalysisMock = ({ style }: { style?: CSSProperties }) => (
  <MockWindow title="AAPL Equity View" style={style}>
    <div
      style={{
        height: "calc(100% - 42px)",
        display: "grid",
        gridTemplateColumns: "1fr 260px",
        gap: 14,
        padding: 18,
        background: "#f6efd9",
      }}
    >
      <div>
        <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
          {["DES", "FA", "GEX", "NEWS"].map((tab, index) => (
            <div
              key={tab}
              style={{
                ...monoFont,
                padding: "8px 12px",
                background: index === 0 ? "#d9c69d" : "rgba(255,255,255,0.5)",
                border: "1px solid rgba(93,72,42,0.17)",
                fontSize: 12,
                fontWeight: 950,
              }}
            >
              {tab}
            </div>
          ))}
        </div>
        <div
          style={{
            height: 230,
            border: "1px solid rgba(93,72,42,0.18)",
            background:
              "linear-gradient(rgba(93,72,42,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(93,72,42,0.08) 1px, transparent 1px), rgba(255,255,255,0.45)",
            backgroundSize: "36px 36px",
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: 24,
              right: 24,
              bottom: 66,
              height: 4,
              background: `linear-gradient(90deg, ${green}, ${accent}, #c34c5d)`,
              transform: "skewY(-7deg)",
              boxShadow: "0 0 20px rgba(49,196,141,0.28)",
            }}
          />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginTop: 12 }}>
          {[
            ["Price", "311.82"],
            ["Signal", "Neutral"],
            ["Risk", "Medium"],
          ].map(([label, value]) => (
            <div
              key={label}
              style={{
                border: "1px solid rgba(93,72,42,0.17)",
                background: "rgba(255,255,255,0.46)",
                padding: 12,
              }}
            >
              <div style={{ ...monoFont, color: "#6d604c", fontSize: 11, fontWeight: 950 }}>
                {label}
              </div>
              <div style={{ fontSize: 20, fontWeight: 950, marginTop: 6 }}>{value}</div>
            </div>
          ))}
        </div>
      </div>
      <div
        style={{
          border: "1px solid rgba(93,72,42,0.18)",
          background: "rgba(255,255,255,0.42)",
          padding: 14,
        }}
      >
        <div style={{ ...monoFont, fontSize: 12, fontWeight: 950 }}>Sources</div>
        {["Market data", "Company filings", "News flow", "Options"].map((source) => (
          <div
            key={source}
            style={{
              display: "flex",
              justifyContent: "space-between",
              borderTop: "1px solid rgba(93,72,42,0.12)",
              padding: "10px 0",
              fontSize: 15,
              fontWeight: 800,
            }}
          >
            <span>{source}</span>
            <span style={{ color: "#168759" }}>live</span>
          </div>
        ))}
      </div>
    </div>
  </MockWindow>
);

const HeroScene = ({ duration }: { duration: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const opacity = sceneOpacity(frame, duration, fps);
  const title = ease(frame, [8, 48], [0, 1]);
  const screen = ease(frame, [20, 72], [0, 1]);

  return (
    <AbsoluteFill style={{ ...baseFont, opacity }}>
      <CockpitMock
        style={{
          width: 1040,
          height: 560,
          right: 84,
          top: 215,
          transform: `translateX(${(1 - screen) * 140}px) scale(${0.94 + screen * 0.06})`,
          opacity: screen,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 100,
          top: 102,
          width: 690,
          transform: `translateY(${(1 - title) * 36}px)`,
          opacity: title,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
          <Img
            src={asset("showme-icon.png")}
            style={{ width: 82, height: 82, borderRadius: 8 }}
          />
          <Eyebrow>macOS market cockpit</Eyebrow>
        </div>
        <div
          style={{
            fontSize: 128,
            lineHeight: 0.9,
            fontWeight: 950,
            marginTop: 32,
            letterSpacing: 0,
          }}
        >
          ShowMe
        </div>
        <div
          style={{
            color: "#e3d8c2",
            fontSize: 45,
            lineHeight: 1.12,
            fontWeight: 780,
            marginTop: 26,
            maxWidth: 620,
          }}
        >
          See the whole market from one desktop. Scans, charts, news,
          portfolios, and bot oversight live in one workflow.
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 104,
          bottom: 112,
          display: "flex",
          gap: 18,
        }}
      >
        <Metric value="3,370" label="symbols in the scan universe" delay={54} />
        <Metric value="12 TF" label="timeframes scanned together" delay={66} />
        <Metric value="141" label="market-engine functions" delay={78} />
      </div>
    </AbsoluteFill>
  );
};

const ScanScene = ({ duration }: { duration: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const opacity = sceneOpacity(frame, duration, fps);
  const copy = ease(frame, [8, 44], [0, 1]);
  const shot = ease(frame, [24, 70], [0, 1]);
  const sweep = linear(frame, [56, 124], [0, 1]);

  return (
    <AbsoluteFill style={{ ...baseFont, opacity }}>
      <div
        style={{
          position: "absolute",
          left: 104,
          top: 112,
          width: 510,
          opacity: copy,
          transform: `translateY(${(1 - copy) * 28}px)`,
        }}
      >
        <Eyebrow color={green}>Multi-Indicator Scan</Eyebrow>
        <div
          style={{
            fontSize: 78,
            lineHeight: 0.98,
            fontWeight: 930,
            marginTop: 24,
          }}
        >
          Spot consensus before the move.
        </div>
        <div
          style={{
            marginTop: 28,
            color: muted,
            fontSize: 29,
            lineHeight: 1.24,
            fontWeight: 680,
          }}
        >
          Scan crypto, equities, ETFs, FX, commodities, and bonds from one fast
          screen.
        </div>
      </div>
      <ScanMock
        style={{
          width: 1190,
          height: 648,
          right: 88,
          top: 246,
          transform: `translateY(${(1 - shot) * 70}px) scale(${0.9 + shot * 0.1})`,
          opacity: shot,
        }}
      />
      <div
        style={{
          position: "absolute",
          right: 180 + sweep * 740,
          top: 246,
          width: 4,
          height: 648,
          background: `linear-gradient(${green}, ${accent})`,
          opacity: shot * 0.32,
          boxShadow: `0 0 34px ${green}`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 104,
          bottom: 106,
          display: "flex",
          gap: 14,
          flexWrap: "wrap",
          width: 610,
        }}
      >
        {["Crypto", "Equities", "ETFs", "FX", "Commodities", "Bonds"].map(
          (label, index) => (
            <CodeChip key={label} active={index < 2}>
              {label}
            </CodeChip>
          ),
        )}
      </div>
    </AbsoluteFill>
  );
};

const FunctionScene = ({ duration }: { duration: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const opacity = sceneOpacity(frame, duration, fps);
  const left = ease(frame, [16, 58], [0, 1]);
  const right = ease(frame, [36, 76], [0, 1]);
  const codes = ["OMON", "GEX", "DES", "PORT", "WATCH", "BOT", "NI", "BTMM"];

  return (
    <AbsoluteFill style={{ ...baseFont, opacity }}>
      <PaletteMock
        style={{
          left: 92,
          top: 198,
          width: 820,
          height: 514,
          transform: `translateX(${(1 - left) * -86}px) rotate(-1deg)`,
          opacity: left,
        }}
      />
      <AnalysisMock
        style={{
          right: 94,
          top: 300,
          width: 848,
          height: 476,
          transform: `translateX(${(1 - right) * 88}px) rotate(1.2deg)`,
          opacity: right,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 104,
          top: 88,
          display: "flex",
          gap: 12,
          opacity: ease(frame, [0, 28], [0, 1]),
        }}
      >
        {codes.map((code, index) => (
          <CodeChip key={code} active={index === Math.floor(frame / 16) % codes.length}>
            {code}
          </CodeChip>
        ))}
      </div>
      <div
        style={{
          position: "absolute",
          left: 392,
          bottom: 104,
          width: 1140,
          padding: "30px 38px",
          borderRadius: 8,
          background: "rgba(12,12,12,0.88)",
          border: "1px solid rgba(244,239,228,0.18)",
          boxShadow: "0 28px 70px rgba(0,0,0,0.35)",
        }}
      >
        <Eyebrow>Function engine</Eyebrow>
        <div style={{ fontSize: 68, fontWeight: 930, lineHeight: 1.02, marginTop: 12 }}>
          141 functions. One command palette. A real analyst workflow.
        </div>
      </div>
    </AbsoluteFill>
  );
};

const FunctionCategory = ({
  title,
  codes,
  detail,
  index,
}: {
  title: string;
  codes: string[];
  detail: string;
  index: number;
}) => {
  const frame = useCurrentFrame();
  const appear = ease(frame, [16 + index * 12, 48 + index * 12], [0, 1]);

  return (
    <div
      style={{
        width: 392,
        minHeight: 170,
        borderRadius: 8,
        border: "1px solid rgba(244,239,228,0.18)",
        background: index % 2 === 0 ? "rgba(244,239,228,0.08)" : "rgba(217,138,61,0.10)",
        padding: "22px 24px",
        opacity: appear,
        transform: `translateY(${(1 - appear) * 34}px)`,
      }}
    >
      <div
        style={{
          ...monoFont,
          color: index % 3 === 2 ? green : accent,
          fontSize: 20,
          fontWeight: 900,
        }}
      >
        {title}
      </div>
      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          marginTop: 18,
        }}
      >
        {codes.map((code, codeIndex) => (
          <div
            key={code}
            style={{
              ...monoFont,
              minWidth: 62,
              height: 34,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 5,
              color: codeIndex === 0 ? "#111" : ink,
              background: codeIndex === 0 ? accent : "rgba(244,239,228,0.10)",
              border: `1px solid ${codeIndex === 0 ? accent : "rgba(244,239,228,0.15)"}`,
              fontSize: 16,
              fontWeight: 950,
            }}
          >
            {code}
          </div>
        ))}
      </div>
      <div style={{ color: muted, fontSize: 19, lineHeight: 1.22, marginTop: 16 }}>
        {detail}
      </div>
    </div>
  );
};

const FunctionCoverageScene = ({ duration }: { duration: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const opacity = sceneOpacity(frame, duration, fps);
  const headline = ease(frame, [8, 42], [0, 1]);
  const count = Math.round(linear(frame, [18, 86], [36, 141]));
  const categories = [
    ["Market data", ["QUOTE", "WATCH", "SCAN", "TOP"], "Live prices, watchlists, scanners, movers."],
    ["Equity research", ["DES", "FA", "DCF", "WACC"], "Description, fundamentals, valuation, cost of capital."],
    ["Options", ["OMON", "GEX", "IVOL", "GREEKS"], "Options monitor, gamma exposure, implied vol, Greeks."],
    ["Portfolio risk", ["PORT", "PVAR", "CORR", "BLAK"], "Allocation, VaR, correlation, Black-Litterman."],
    ["Macro and rates", ["BTMM", "WIRP", "ECO", "YAS"], "Rates, events, calendars, yield spread analysis."],
    ["News and bots", ["NI", "BRIEF", "BOT", "ALRT"], "News intelligence, briefs, alerts, bot supervision."],
  ] as const;

  return (
    <AbsoluteFill style={{ ...baseFont, opacity }}>
      <div
        style={{
          position: "absolute",
          left: 104,
          top: 80,
          width: 1020,
          opacity: headline,
          transform: `translateY(${(1 - headline) * 30}px)`,
        }}
      >
        <Eyebrow color={green}>Function coverage</Eyebrow>
        <div style={{ fontSize: 84, fontWeight: 940, lineHeight: 0.98, marginTop: 22 }}>
          Dozens of finance functions, ready from one surface.
        </div>
        <div style={{ color: muted, fontSize: 29, lineHeight: 1.24, marginTop: 24, width: 820 }}>
          ShowMe is not just a dashboard. It is a command-driven analyst desk
          for market data, options, risk, macro, news, alerts, and bots.
        </div>
      </div>
      <div
        style={{
          ...monoFont,
          position: "absolute",
          right: 112,
          top: 92,
          width: 330,
          height: 160,
          borderRadius: 8,
          border: "1px solid rgba(244,239,228,0.18)",
          background: "rgba(244,239,228,0.08)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          opacity: headline,
        }}
      >
        <div style={{ color: accent, fontSize: 76, fontWeight: 950 }}>{count}</div>
        <div style={{ color: muted, fontSize: 18, fontWeight: 900 }}>market functions</div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 104,
          top: 530,
          display: "grid",
          gridTemplateColumns: "repeat(3, 392px)",
          gap: 22,
        }}
      >
        {categories.map(([title, codes, detail], index) => (
          <FunctionCategory
            key={title}
            title={title}
            codes={[...codes]}
            detail={detail}
            index={index}
          />
        ))}
      </div>
    </AbsoluteFill>
  );
};

const OutroScene = ({ duration }: { duration: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const opacity = sceneOpacity(frame, duration, fps);
  const title = ease(frame, [18, 58], [0, 1]);
  const zoom = linear(frame, [0, duration], [1, 1.045]);

  return (
    <AbsoluteFill style={{ ...baseFont, opacity }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          transform: `scale(${zoom})`,
          opacity: 0.62,
        }}
      >
        <CockpitMock
          style={{ left: -60, top: 116, width: 900, height: 486, opacity: 0.84 }}
        />
        <ScanMock
          style={{ right: -40, top: 86, width: 930, height: 506, opacity: 0.9 }}
        />
        <AnalysisMock
          style={{ left: 390, bottom: 74, width: 1080, height: 588, opacity: 0.82 }}
        />
      </div>
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(90deg, rgba(9,10,12,0.94), rgba(9,10,12,0.72), rgba(9,10,12,0.94))",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 230,
          textAlign: "center",
          opacity: title,
          transform: `translateY(${(1 - title) * 44}px)`,
        }}
      >
        <Img src={asset("showme-icon.png")} style={{ width: 96, height: 96, borderRadius: 8 }} />
        <div style={{ fontSize: 142, fontWeight: 960, lineHeight: 0.95, marginTop: 28 }}>
          ShowMe
        </div>
        <div
          style={{
            color: "#eee0c9",
            fontSize: 52,
            fontWeight: 780,
            marginTop: 28,
          }}
        >
          See the market in one place.
        </div>
        <div
          style={{
            ...monoFont,
            color: muted,
            fontSize: 26,
            fontWeight: 850,
            marginTop: 34,
          }}
        >
          macOS | local-first | open source | no broker lock-in
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const ShowMePromo = () => {
  const { fps } = useVideoConfig();
  const hero = seconds(5, fps);
  const scan = seconds(5, fps);
  const fn = seconds(5, fps);
  const flow = seconds(4, fps);
  const outro = seconds(5, fps);

  return (
    <AbsoluteFill style={baseFont}>
      <AmbientGrid />
      <Sequence durationInFrames={hero}>
        <HeroScene duration={hero} />
      </Sequence>
      <Sequence from={hero} durationInFrames={scan}>
        <ScanScene duration={scan} />
      </Sequence>
      <Sequence from={hero + scan} durationInFrames={fn}>
        <FunctionScene duration={fn} />
      </Sequence>
      <Sequence from={hero + scan + fn} durationInFrames={flow}>
        <FunctionCoverageScene duration={flow} />
      </Sequence>
      <Sequence from={hero + scan + fn + flow} durationInFrames={outro}>
        <OutroScene duration={outro} />
      </Sequence>
    </AbsoluteFill>
  );
};
