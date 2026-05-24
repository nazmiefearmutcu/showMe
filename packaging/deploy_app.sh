#!/usr/bin/env bash
# Install the latest packaged showMe.app while keeping exactly one previous app.
#
# REL-04 P12 — optionally invokes packaging/sign.sh and packaging/notarize.sh
# when an Apple Developer ID is in the environment. Without those env vars
# we skip cleanly so local dev keeps working with the ad-hoc signature.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
SOURCE="${1:-$ROOT/tauri/target/release/bundle/macos/showMe.app}"
DMG_SOURCE_DIR="${SHOWME_DMG_DIR:-$ROOT/tauri/target/release/bundle/dmg}"
TARGET="${SHOWME_APP_TARGET:-/Applications/showMe.app}"
PREVIOUS="${SHOWME_APP_PREVIOUS:-/Applications/showMe.previous.app}"
LEGACY_BACKUPS_DIR="/Applications/showMe.app.backups"

if [[ ! -d "$SOURCE" ]]; then
  echo "showMe bundle not found at $SOURCE" >&2
  echo "Run npm run tauri:build first, or pass the .app bundle path." >&2
  exit 1
fi

cleanup_legacy_backups() {
  find /Applications -maxdepth 1 \
    \( -name 'showMe.app.bak-*' -o -name 'showMe.app.backup-*' \) \
    -exec rm -rf {} +
  rm -rf "$LEGACY_BACKUPS_DIR"
}

# REL-04 P12 — Developer-ID sign + notarize, when credentials are present.
# We deliberately *do not* fail when env vars are missing — that's the
# expected state on a local dev machine that signs ad-hoc. Releases must
# have the env vars set in CI (see .github/workflows/codesign-gate.yml).
maybe_sign_and_notarize() {
  if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
    echo "→ Developer ID detected — invoking packaging/sign.sh"
    APP_PATH="$SOURCE" bash "$ROOT/packaging/sign.sh"
    if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
      DMG_PATH="$(ls -1 "$DMG_SOURCE_DIR"/*.dmg 2>/dev/null | head -1 || true)"
      if [[ -n "$DMG_PATH" && -f "$DMG_PATH" ]]; then
        echo "→ notarize credentials detected — invoking packaging/notarize.sh"
        APP_PATH="$SOURCE" DMG_PATH="$DMG_PATH" bash "$ROOT/packaging/notarize.sh"
      else
        echo "→ no .dmg found in $DMG_SOURCE_DIR — skipping notarize"
      fi
    else
      echo "→ APPLE_ID / APPLE_TEAM_ID / APPLE_APP_SPECIFIC_PASSWORD missing — skipping notarize"
    fi
  else
    echo "→ APPLE_SIGNING_IDENTITY not set — using existing (ad-hoc) signature"
    echo "  (CI release builds must set APPLE_SIGNING_IDENTITY + APPLE_ID + APPLE_TEAM_ID + APPLE_APP_SPECIFIC_PASSWORD)"
  fi
}

maybe_sign_and_notarize

if [[ -d "$TARGET" ]]; then
  rm -rf "$PREVIOUS"
  /usr/bin/ditto "$TARGET" "$PREVIOUS"
  echo "previous retained -> $PREVIOUS"
else
  rm -rf "$PREVIOUS"
  echo "no installed showMe.app found; no previous copy retained"
fi

rm -rf "$TARGET"
/usr/bin/ditto "$SOURCE" "$TARGET"
cleanup_legacy_backups

# REL-04 P12 — post-install verification. We allow this to fail without
# aborting the deploy (otherwise a local ad-hoc sign would block every
# `npm run deploy:app` invocation) but report the status loudly so a
# regression gets noticed.
if /usr/bin/codesign --verify --strict --verbose=2 "$TARGET" 2>&1; then
  echo "post-install codesign verify: OK"
else
  echo "WARNING: post-install codesign verify failed (ad-hoc sign is expected without APPLE_SIGNING_IDENTITY)" >&2
fi

echo "installed -> $TARGET"
echo "retention -> current + one previous only"
