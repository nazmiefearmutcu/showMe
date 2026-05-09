#!/usr/bin/env bash
# Build the PyInstaller sidecar binary that the Tauri shell launches.
#
# Output:
#   src-tauri/binaries/showme-backend  (arm64 on Apple Silicon)
#
# Requirements:
#   - uv
#   - ShowMe's bundled engine at $SHOWME_ENGINE_PATH (default ./engine).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
ENGINE_PATH="${SHOWME_ENGINE_PATH:-$ROOT/engine}"
VERYFINDER_PATH="${SHOWME_VERYFINDER_ROOT:-$HOME/Desktop/Projeler/veryfinder}"
DIST="$ROOT/src-tauri/binaries"
mkdir -p "$DIST"

if [[ ! -d "$ENGINE_PATH/src" ]]; then
  echo "ShowMe engine not found at $ENGINE_PATH — set SHOWME_ENGINE_PATH" >&2
  exit 1
fi

VERYFINDER_ARGS=()
if [[ -f "$VERYFINDER_PATH/veryfinder/orchestrator.py" ]]; then
  VERYFINDER_ARGS+=(
    --add-data "$VERYFINDER_PATH/veryfinder:integrations/veryfinder/veryfinder"
  )
  if [[ -d "$VERYFINDER_PATH/data" ]]; then
    VERYFINDER_ARGS+=(--add-data "$VERYFINDER_PATH/data:integrations/veryfinder/data")
  fi
  echo "Including Veryfinder runtime from $VERYFINDER_PATH"
else
  echo "Veryfinder runtime not found at $VERYFINDER_PATH; sidecar will use Application Support cache if present." >&2
fi

pushd "$ROOT/src-py" >/dev/null

uv run --extra dev python -m PyInstaller \
  --name showme-backend \
  --onefile \
  --noconfirm \
  --clean \
  --paths "$ENGINE_PATH" \
  --add-data "$ENGINE_PATH/src:src" \
  --add-data "$ENGINE_PATH/config:config" \
  --collect-submodules src \
  --collect-submodules yfinance \
  --collect-data yfinance \
  --collect-submodules lxml \
  --hidden-import feedparser \
  --hidden-import lxml \
  --hidden-import sgmllib \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.protocols \
  --hidden-import uvicorn.lifespan.on \
  "${VERYFINDER_ARGS[@]}" \
  --target-arch arm64 \
  showme/server.py

cp dist/showme-backend "$DIST/showme-backend"
chmod +x "$DIST/showme-backend"
cp dist/showme-backend "$DIST/showme-backend-aarch64-apple-darwin"
chmod +x "$DIST/showme-backend-aarch64-apple-darwin"

popd >/dev/null

echo "✓ sidecar built → $DIST/showme-backend"
echo "✓ tauri externalBin → $DIST/showme-backend-aarch64-apple-darwin"
echo "  next: codesign with Developer ID + hardened runtime + allow-jit entitlement."
