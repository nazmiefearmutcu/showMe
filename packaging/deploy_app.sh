#!/usr/bin/env bash
# Install the latest packaged showMe.app while keeping exactly one previous app.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
SOURCE="${1:-$ROOT/tauri/target/release/bundle/macos/showMe.app}"
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

echo "installed -> $TARGET"
echo "retention -> current + one previous only"
