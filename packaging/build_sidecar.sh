#!/usr/bin/env bash
# Build the PyInstaller sidecar bundle that the Tauri shell launches.
#
# PERF-06 R3A: switched from PyInstaller --onefile to --onedir.
# The output is now a directory rather than a single megabyte binary.
#
# Output (post-PERF-06):
#   tauri/binaries/showme-backend/                       (onedir bundle, arm64)
#   tauri/binaries/showme-backend-aarch64-apple-darwin/  (same bundle, Tauri externalBin layout)
#
# Each bundle directory contains a `showme-backend` launcher binary that the
# Tauri shell resolves via the externalBin reference. The launcher loads
# the rest of the runtime (Python + dependency wheels + bundled X-Sentiment
# model) from the SAME directory it lives in — no re-extraction into /tmp.
# Cold start drops from ≈7 s (onefile) to under 5 s (onedir).
#
# Requirements:
#   - uv
#   - The unified Python backend at backend/showme/engine/
#   - The PyInstaller spec at backend/showme-backend.spec is already
#     configured for onedir (EXE(exclude_binaries=True) + COLLECT(...)),
#     wires --add-data, --collect-submodules, hidden imports, and the
#     optional veryfinder integration.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
BACKEND="$ROOT/backend"
DIST="$ROOT/tauri/binaries"
mkdir -p "$DIST"

if [[ ! -d "$BACKEND/showme/engine" ]]; then
  echo "Unified backend not found at $BACKEND/showme/engine" >&2
  echo "Expected the showme.engine subpackage created by the unified-tree refactor." >&2
  exit 1
fi

pushd "$BACKEND" >/dev/null

# The spec file collects everything (showme.* submodules, yfinance data,
# optional veryfinder integration). Just run it in --clean mode.
uv run --extra dev python -m PyInstaller \
  --noconfirm \
  --clean \
  showme-backend.spec

if [[ ! -d "dist/showme-backend" ]]; then
  echo "PyInstaller did not emit dist/showme-backend/ — onedir build failed" >&2
  exit 2
fi
if [[ ! -x "dist/showme-backend/showme-backend" ]]; then
  echo "Launcher executable dist/showme-backend/showme-backend missing or not executable" >&2
  exit 3
fi

popd >/dev/null

# If a previous --onefile build left a regular file at the externalBin
# path, rsync into the same name would fail with "Not a directory". Clear
# any non-directory holdover before mirroring the new onedir bundle.
for dest in "$DIST/showme-backend" "$DIST/showme-backend-aarch64-apple-darwin"; do
  if [[ -e "$dest" && ! -d "$dest" ]]; then
    rm -f "$dest"
  fi
done
mkdir -p "$DIST/showme-backend" "$DIST/showme-backend-aarch64-apple-darwin"

# Mirror the onedir bundle into both Tauri externalBin locations. rsync
# with --delete keeps the destination layout exactly matching dist/ so a
# previous onefile binary can't linger and shadow the new launcher.
rsync -a --delete "$BACKEND/dist/showme-backend/" "$DIST/showme-backend/"
rsync -a --delete "$BACKEND/dist/showme-backend/" "$DIST/showme-backend-aarch64-apple-darwin/"

chmod +x "$DIST/showme-backend/showme-backend"
chmod +x "$DIST/showme-backend-aarch64-apple-darwin/showme-backend"

echo "✓ sidecar bundle built → $DIST/showme-backend/"
echo "✓ tauri externalBin    → $DIST/showme-backend-aarch64-apple-darwin/"
echo "  launcher binary:     $DIST/showme-backend/showme-backend"

# PERF-06 R3C — Tauri 2.x rejects an externalBin entry that points at a
# directory ("expected a file"). Once the sidecar is in --onedir form we
# need to migrate `bundle.externalBin: ["binaries/showme-backend"]` →
# `bundle.resources: ["binaries/showme-backend/**/*"]`. This block does
# the swap idempotently using uv-managed Python so the operator never
# has to remember to edit JSON by hand. The Rust sidecar
# (`tauri/src/sidecar.rs::resolve_bundled_sidecar`) already auto-detects
# the new Contents/Resources/binaries/showme-backend/ path, so flipping
# the config is the only remaining wire-up.
CONF="$ROOT/tauri/tauri.conf.json"
if [[ -f "$CONF" ]]; then
  uv run python - "$CONF" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
bundle = data.setdefault("bundle", {})
ext = bundle.get("externalBin", [])
res = bundle.get("resources", [])
target_glob = "binaries/showme-backend/**/*"
changed = False
# Drop legacy externalBin entries that point at the sidecar bundle.
new_ext = [e for e in ext if e not in ("binaries/showme-backend",)]
if new_ext != ext:
    bundle["externalBin"] = new_ext
    changed = True
# Add the resources glob if missing.
if isinstance(res, list) and target_glob not in res:
    res.append(target_glob)
    bundle["resources"] = res
    changed = True
elif not isinstance(res, list):
    bundle["resources"] = [target_glob]
    changed = True
if changed:
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"✓ tauri.conf.json updated for --onedir layout")
else:
    print(f"  tauri.conf.json already on --onedir layout")
PY
fi

echo "  next: codesign with Developer ID + hardened runtime + allow-jit entitlement."
