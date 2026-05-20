#!/usr/bin/env bash
# Submit the signed .dmg to Apple notarization, then staple.
#
# TEST-09 P2 — also signs the DMG itself before submission (Apple no
# longer auto-signs DMGs, and Sparkle-style delta channels reject
# unsigned ones), captures the submission ID for `notarytool log`, and
# also staples the inner .app so first-launch on an offline machine
# doesn't hit Gatekeeper's online verifier.
#
# Required env:
#   APPLE_ID                  Apple developer account email
#   APPLE_TEAM_ID             Team ID (10 chars)
#   APPLE_APP_SPECIFIC_PASSWORD  app-specific password from appleid.apple.com
#   APPLE_SIGNING_IDENTITY    Developer ID Application identity (for DMG sign)
#   DMG_PATH                  path to the dmg (default: tauri/target/.../*.dmg)
#   APP_PATH                  optional path to .app for inner-staple

set -euo pipefail

DMG_PATH="${DMG_PATH:-$(ls -1 tauri/target/release/bundle/dmg/*.dmg 2>/dev/null | head -1)}"
APP_PATH="${APP_PATH:-$(ls -1 tauri/target/release/bundle/macos/*.app 2>/dev/null | head -1)}"
APPLE_ID="${APPLE_ID:?APPLE_ID env var required}"
APPLE_TEAM_ID="${APPLE_TEAM_ID:?APPLE_TEAM_ID env var required}"
APPLE_APP_SPECIFIC_PASSWORD="${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD env var required}"
APPLE_SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:-}"

if [[ -z "$DMG_PATH" || ! -f "$DMG_PATH" ]]; then
  echo "DMG not found — set DMG_PATH or run 'cargo tauri build' first." >&2
  exit 1
fi

if [[ -n "$APPLE_SIGNING_IDENTITY" ]]; then
  echo "→ signing DMG"
  codesign --sign "$APPLE_SIGNING_IDENTITY" --timestamp "$DMG_PATH"
fi

echo "→ submitting $DMG_PATH for notarization"
SUBMISSION_LOG="$(mktemp -t showme-notarize-XXXXXX.json)"
trap 'rm -f "$SUBMISSION_LOG"' EXIT
xcrun notarytool submit "$DMG_PATH" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD" \
  --output-format json \
  --wait \
  | tee "$SUBMISSION_LOG"

STATUS="$(python3 -c "import json,sys; print(json.load(open('$SUBMISSION_LOG'))['status'])" 2>/dev/null || echo unknown)"
SUB_ID="$(python3 -c "import json,sys; print(json.load(open('$SUBMISSION_LOG'))['id'])" 2>/dev/null || echo)"

if [[ "$STATUS" != "Accepted" ]]; then
  echo "notarization failed (status=$STATUS, id=$SUB_ID)" >&2
  if [[ -n "$SUB_ID" ]]; then
    xcrun notarytool log "$SUB_ID" \
      --apple-id "$APPLE_ID" \
      --team-id "$APPLE_TEAM_ID" \
      --password "$APPLE_APP_SPECIFIC_PASSWORD" >&2 || true
  fi
  exit 1
fi

echo "→ stapling DMG"
xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"

if [[ -n "$APP_PATH" && -d "$APP_PATH" ]]; then
  echo "→ stapling inner .app at $APP_PATH"
  xcrun stapler staple "$APP_PATH"
  xcrun stapler validate "$APP_PATH"
fi

echo "→ post-deploy codesign verification"
if [[ -n "$APP_PATH" && -d "$APP_PATH" ]]; then
  codesign --verify --strict --verbose=2 "$APP_PATH"
fi
codesign --verify --strict --verbose=2 "$DMG_PATH" || true

echo "✓ notarized: $DMG_PATH"
