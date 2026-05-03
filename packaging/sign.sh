#!/usr/bin/env bash
# Sign the showMe.app bundle (and the embedded sidecar) with a Developer ID.
#
# Required env:
#   APPLE_SIGNING_IDENTITY   "Developer ID Application: ACME Inc (TEAMID)"
#   APP_PATH                 path to showMe.app (defaults to release dir)

set -euo pipefail

APP_PATH="${APP_PATH:-$PWD/src-tauri/target/release/bundle/macos/showMe.app}"
IDENTITY="${APPLE_SIGNING_IDENTITY:?APPLE_SIGNING_IDENTITY env var required}"
ENTITLEMENTS="${ENTITLEMENTS:-$PWD/src-tauri/entitlements.plist}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Bundle not found at $APP_PATH — build first with 'cargo tauri build'." >&2
  exit 1
fi

echo "→ signing sidecar"
codesign --force --options runtime \
  --entitlements "$ENTITLEMENTS" \
  --sign "$IDENTITY" \
  --timestamp \
  "$APP_PATH/Contents/MacOS/showme-backend" || true

echo "→ signing helpers"
find "$APP_PATH/Contents/Frameworks" -name "*.dylib" -print0 2>/dev/null \
  | xargs -0 -I{} codesign --force --options runtime --sign "$IDENTITY" --timestamp {} || true

echo "→ signing main bundle"
codesign --force --deep --options runtime \
  --entitlements "$ENTITLEMENTS" \
  --sign "$IDENTITY" \
  --timestamp \
  "$APP_PATH"

echo "→ verifying"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
spctl --assess --type execute --verbose=2 "$APP_PATH" || true

echo "✓ signed: $APP_PATH"
