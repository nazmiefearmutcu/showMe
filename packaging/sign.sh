#!/usr/bin/env bash
# Sign the showMe.app bundle (and the embedded sidecar) with a Developer ID.
#
# TEST-09 P1 — bottom-up signing: every nested Mach-O / .dylib / .so
# is signed in dependency order with the same hardened-runtime
# entitlements before the outer bundle is signed. We do NOT use
# `--deep` (Apple deprecated it; it re-signs nested binaries with the
# OUTER entitlements which can corrupt the sidecar's expected runtime
# attributes). We also drop every `|| true` swallow so a real signing
# failure never gets hidden behind a green log line.
#
# Required env:
#   APPLE_SIGNING_IDENTITY   "Developer ID Application: ACME Inc (TEAMID)"
#   APP_PATH                 path to showMe.app (defaults to release dir)

set -euo pipefail

APP_PATH="${APP_PATH:-$PWD/tauri/target/release/bundle/macos/showMe.app}"
IDENTITY="${APPLE_SIGNING_IDENTITY:?APPLE_SIGNING_IDENTITY env var required}"
ENTITLEMENTS="${ENTITLEMENTS:-$PWD/tauri/entitlements.plist}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Bundle not found at $APP_PATH — build first with 'cargo tauri build'." >&2
  exit 1
fi

sign_one() {
  local target="$1"
  echo "  · sign $target"
  codesign --force --options runtime \
    --entitlements "$ENTITLEMENTS" \
    --sign "$IDENTITY" \
    --timestamp \
    "$target"
}

echo "→ signing nested Mach-O (frameworks, dylibs, .so extension modules)"
# Sort -r so deepest paths come first — bottom-up signing is required by
# Apple's strict notarisation pass.
while IFS= read -r path; do
  sign_one "$path"
done < <(
  find "$APP_PATH/Contents" \
    \( -name '*.dylib' -o -name '*.so' -o -name '*.framework' \) \
    -print 2>/dev/null \
    | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2-
)

echo "→ signing PyInstaller _internal/ binaries"
if [[ -d "$APP_PATH/Contents/MacOS/_internal" ]]; then
  while IFS= read -r path; do
    sign_one "$path"
  done < <(
    find "$APP_PATH/Contents/MacOS/_internal" -type f -perm -u+x -print
  )
fi

echo "→ signing sidecar"
sign_one "$APP_PATH/Contents/MacOS/showme-backend"

echo "→ signing main bundle (no --deep)"
codesign --force --options runtime \
  --entitlements "$ENTITLEMENTS" \
  --sign "$IDENTITY" \
  --timestamp \
  "$APP_PATH"

echo "→ verifying"
codesign --verify --strict --verbose=2 "$APP_PATH"
spctl --assess --type execute --verbose=2 "$APP_PATH"

echo "✓ signed: $APP_PATH"
