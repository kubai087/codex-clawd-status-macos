#!/bin/bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$root"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "build requires an Apple silicon Mac" >&2
  exit 1
fi

rm -rf "$root/build" "$root/dist"
"$root/.venv/bin/pyinstaller" --noconfirm "$root/packaging/clawd-status.spec"
codesign --force --deep --sign - "$root/dist/clawd-status/clawd-status"

mkdir -p \
  "$root/dist/payload/bin" \
  "$root/dist/payload/share/codex-clawd-status"
cp -R "$root/dist/clawd-status" "$root/dist/payload/runtime"
ln -s ../runtime/clawd-status "$root/dist/payload/bin/clawd-status"
cp -R \
  "$root/vendor/codex-status-LED" \
  "$root/dist/payload/share/codex-clawd-status/skill"
cp \
  "$root/vendor/codex-status-LED/LICENSE" \
  "$root/dist/payload/share/codex-clawd-status/LICENSE"
cp \
  "$root/THIRD_PARTY_NOTICES" \
  "$root/dist/payload/share/codex-clawd-status/THIRD_PARTY_NOTICES"

"$root/dist/payload/bin/clawd-status" --version
