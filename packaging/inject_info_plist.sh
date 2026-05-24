#!/usr/bin/env bash
# SEC-15: Inject TCC NSUsageDescription keys into the deployed showMe.app.
#
# Background: Tauri 2 has no first-class field for these usage strings, so
# the Info.plist Tauri generates lacks NSDesktopFolderUsageDescription &
# friends. On macOS 12+ the TCC daemon silently HANGS open() syscalls from
# the sidecar the first time it tries to read user-domain folders without
# a matching purpose string — the same incident burned Catchem (see memory
# entry `catchem_app_boot`). This script injects the four strings the
# sidecar's data adapters can reach (Desktop, Downloads, Documents, Apple
# Events) and re-signs ad-hoc so the bundle stays valid.
#
# Usage: bash packaging/inject_info_plist.sh /Applications/showMe.app
#
# Idempotent: re-running on an already-injected bundle is a no-op (plutil
# -replace overwrites the same value).
set -euo pipefail

APP_PATH="${1:-/Applications/showMe.app}"
PLIST="$APP_PATH/Contents/Info.plist"

if [[ ! -f "$PLIST" ]]; then
  echo "inject_info_plist: $PLIST not found" >&2
  exit 1
fi

inject() {
  local key="$1"
  local value="$2"
  /usr/bin/plutil -replace "$key" -string "$value" "$PLIST"
}

inject NSDesktopFolderUsageDescription \
  "showMe reads market data files you save to the Desktop (CSV exports, alert templates)."
inject NSDownloadsFolderUsageDescription \
  "showMe imports downloaded broker statements and exports reports to the Downloads folder."
inject NSDocumentsFolderUsageDescription \
  "showMe stores your strategy library, watchlists, and bot configurations under Documents."
inject NSAppleEventsUsageDescription \
  "showMe uses AppleScript to surface OS notifications and keep the Dock tile in sync."

# Re-sign ad-hoc so the modified Info.plist doesn't break codesign --verify.
# Real release builds set APPLE_SIGNING_IDENTITY and run packaging/sign.sh
# AFTER this script (see deploy_app.sh order).
if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  /usr/bin/codesign --force --sign - "$APP_PATH" >/dev/null 2>&1 || {
    echo "inject_info_plist: ad-hoc re-sign failed (non-fatal in dev)" >&2
  }
fi

echo "→ injected 4 NSUsageDescription keys into $PLIST"
