/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import csp from "vite-plugin-csp-guard";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Tauri exposes specific env hooks; see https://tauri.app/v2/reference/config/.
const host = process.env.TAURI_DEV_HOST;
const __dirname = path.dirname(fileURLToPath(import.meta.url));

function manualChunks(id: string): string | undefined {
  if (id.includes("/node_modules/react") || id.includes("/node_modules/scheduler")) {
    return "vendor-react";
  }
  if (id.includes("/node_modules/@tauri-apps/")) {
    return "vendor-tauri";
  }
  if (id.includes("/node_modules/lightweight-charts/")) {
    return "vendor-charts";
  }
  if (id.includes("/node_modules/")) {
    return "vendor";
  }
  if (id.includes("/src/functions/")) {
    return `fn-${path.basename(id).replace(/\.(tsx?|jsx?)$/, "")}`;
  }
  if (id.includes("/src/panes/")) {
    return `pane-${path.basename(id).replace(/\.(tsx?|jsx?)$/, "")}`;
  }
  return undefined;
}

export default defineConfig({
  // Round-4A CSP wire-up — the csp plugin emits a per-build nonce, injects it
  // into `<style>` blocks, and ships a Content-Security-Policy meta tag. The
  // Tauri sibling reads the meta tag at startup so the runtime policy stays
  // in sync with what the build was hashed against. See ui/CSP.md.
  plugins: [
    react(),
    csp({
      algorithm: "sha256",
      dev: {
        run: false,
      },
      policy: {
        "default-src": ["'self'"],
        "img-src": ["'self'", "data:", "blob:"],
        "style-src": ["'self'"],
        "script-src": ["'self'"],
        "connect-src": ["'self'", "ws:", "wss:", "http://localhost:*", "http://127.0.0.1:*"],
        "font-src": ["'self'", "data:"],
      },
    }),
  ],
  clearScreen: false,
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    host: host || false,
    hmr: host
      ? { protocol: "ws", host, port: 5174 }
      : undefined,
    watch: { ignored: ["**/tauri/target/**", "**/tauri/binaries/**"] },
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari15",
    minify: !process.env.TAURI_ENV_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
