import { useAppStore } from "@/lib/store";

export function Splash() {
  const status = useAppStore((s) => s.sidecarStatus);
  const engine = useAppStore((s) => s.engineRoot);
  const total = useAppStore((s) => s.functionIndex.length);

  return (
    <main
      style={{
        padding: 24,
        display: "grid",
        gridTemplateColumns: "1fr",
        gridAutoRows: "min-content",
        gap: 16,
        overflowY: "auto",
      }}
    >
      <header>
        <h1
          style={{
            fontFamily: "Inter, SF Pro Text, system-ui",
            fontSize: 22,
            margin: 0,
            letterSpacing: 0,
          }}
        >
          showMe
          <span style={{ color: "var(--text-mute)", fontWeight: 400, marginLeft: 8 }}>
            market cockpit
          </span>
        </h1>
        <p
          style={{
            color: "var(--text-secondary)",
            fontSize: 13,
            maxWidth: 720,
            marginTop: 4,
          }}
        >
          Native macOS app hosting the Python market engine ({total || "—"} functions).
        </p>
      </header>

      <section className="surface" style={{ padding: 16 }}>
        <h2
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            color: "var(--accent)",
            margin: 0,
            textTransform: "uppercase",
          }}
        >
          Runtime
        </h2>
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "120px 1fr",
            gap: "6px 16px",
            marginTop: 8,
            fontSize: 12,
          }}
        >
          <dt style={{ color: "var(--text-mute)" }}>status</dt>
          <dd style={{ margin: 0, color: "var(--text-primary)" }}>{status}</dd>

          <dt style={{ color: "var(--text-mute)" }}>engine root</dt>
          <dd
            style={{
              margin: 0,
              fontFamily: "JetBrains Mono, monospace",
              color: "var(--text-secondary)",
            }}
          >
            {engine || "(not attached)"}
          </dd>

          <dt style={{ color: "var(--text-mute)" }}>functions</dt>
          <dd style={{ margin: 0 }}>{total}</dd>
        </dl>
      </section>

      <section className="surface" style={{ padding: 16 }}>
        <h2
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            color: "var(--accent)",
            margin: 0,
            textTransform: "uppercase",
          }}
        >
          Quality standard
        </h2>
        <ul
          style={{
            color: "var(--text-secondary)",
            fontSize: 12,
            paddingLeft: 16,
            marginTop: 8,
          }}
        >
          <li>Function payloads come from the Python engine.</li>
          <li>Provider failures are surfaced with next actions.</li>
          <li>Settings persist theme, accent, density, language, secrets, and install controls.</li>
          <li>Every function exposes an info panel with usage steps.</li>
        </ul>
      </section>
    </main>
  );
}
