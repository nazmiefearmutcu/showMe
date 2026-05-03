#!/usr/bin/env bash
# Submit the signed .dmg to Apple notarization, then staple.
#
# Required env:
#   APPLE_ID                  Apple developer account email
#   APPLE_TEAM_ID             Team ID (10 chars)
#   APPLE_APP_SPECIFIC_PASSWORD  app-specific password from appleid.apple.com
#   DMG_PATH                  path to the dmg (default: src-tauri/target/.../*.dmg)

set -euo pipefail

DMG_PATH="${DMG_PATH:-$(ls -1 src-tauri/target/release/bundle/dmg/*.dmg 2>/dev/null | head -1)}"
APPLE_ID="${APPLE_ID:?APPLE_ID env var required}"
APPLE_TEAM_ID="${APPLE_TEAM_ID:?APPLE_TEAM_ID env var required}"
APPLE_APP_SPECIFIC_PASSWORD="${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD env var required}"

if [[ -z "$DMG_PATH" || ! -f "$DMG_PATH" ]]; then
  echo "DMG not found — set DMG_PATH or run 'cargo tauri build' first." >&2
  exit 1
fi

echo "→ submitting $DMG_PATH for notarization"
xcrun notarytool submit "$DMG_PATH" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD" \
  --wait

echo "→ stapling notarization ticket"
xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"

echo "✓ notarized: $DMG_PATH"
