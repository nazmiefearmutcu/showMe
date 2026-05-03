import { useEffect, useState } from "react";
import { useAppStore } from "@/lib/store";
import { isInTauri } from "@/lib/tauri";

export function Statusbar() {
  const status = useAppStore((s) => s.sidecarStatus);
  const port = useAppStore((s) => s.sidecarPort);
  const engineRoot = useAppStore((s) => s.engineRoot);
  const total = useAppStore((s) => s.functionIndex.length);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const utc = now.toISOString().slice(11, 19) + " UTC";

  return (
    <footer className="statusbar">
      <span>app · {isInTauri() ? "native" : "preview"}</span>
      <span>
        runtime · <strong style={{ color: "var(--text-primary)" }}>{status}</strong>
        {port && <span style={{ marginLeft: 4 }}>:{port}</span>}
      </span>
      <span>functions · {total}</span>
      <span style={{ flex: 1, color: "var(--text-mute)" }}>
        data · {engineRoot || "—"}
      </span>
      <span style={{ color: "var(--text-primary)" }}>{utc}</span>
    </footer>
  );
}
