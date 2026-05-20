import { useAppStore } from "@/lib/store";

export function Splash() {
  const status = useAppStore((s) => s.sidecarStatus);
  const engine = useAppStore((s) => s.engineRoot);
  const total = useAppStore((s) => s.functionIndex.length);

  return (
    <main className="splash-main">
      <header>
        <h1 className="splash-main__h1">
          show
          <span className="u-text-accent-strong">Me</span>
          <span className="splash-main__h1-tag">market cockpit</span>
        </h1>
        <p className="splash-main__lede">
          Native macOS app hosting the Python market engine ({total || "—"} functions).
        </p>
      </header>

      <section className="surface splash-main__card">
        <h2 className="splash-main__h2">Runtime</h2>
        <dl className="splash-main__dl">
          <dt className="u-text-mute">status</dt>
          <dd className="splash-main__dd splash-main__dd--primary">{status}</dd>

          <dt className="u-text-mute">engine root</dt>
          <dd className="splash-main__dd splash-main__dd--mono">{engine || "(not attached)"}</dd>

          <dt className="u-text-mute">functions</dt>
          <dd className="splash-main__dd">{total}</dd>
        </dl>
      </section>

      <section className="surface splash-main__card">
        <h2 className="splash-main__h2">Quality standard</h2>
        <ul className="splash-main__list">
          <li>Function payloads come from the Python engine.</li>
          <li>Provider failures are surfaced with next actions.</li>
          <li>Settings persist theme, accent, density, language, secrets, and install controls.</li>
          <li>Every function exposes an info panel with usage steps.</li>
        </ul>
      </section>
    </main>
  );
}
