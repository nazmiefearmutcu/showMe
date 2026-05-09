#!/usr/bin/env bash
# Build the PyInstaller sidecar binary that the Tauri shell launches.
#
# Output:
#   tauri/binaries/showme-backend                       (arm64 on Apple Silicon)
#   tauri/binaries/showme-backend-aarch64-apple-darwin  (Tauri externalBin name)
#
# Requirements:
#   - uv
#   - The unified Python backend at backend/showme/engine/
#   - The PyInstaller spec at backend/showme-backend.spec already wires
#     --add-data, --collect-submodules, hidden imports, and optional
#     veryfinder integration (auto-detected as a sibling project).

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

cp dist/showme-backend "$DIST/showme-backend"
chmod +x "$DIST/showme-backend"
cp dist/showme-backend "$DIST/showme-backend-aarch64-apple-darwin"
chmod +x "$DIST/showme-backend-aarch64-apple-darwin"

popd >/dev/null

echo "✓ sidecar built → $DIST/showme-backend"
echo "✓ tauri externalBin → $DIST/showme-backend-aarch64-apple-darwin"
echo "  next: codesign with Developer ID + hardened runtime + allow-jit entitlement."
