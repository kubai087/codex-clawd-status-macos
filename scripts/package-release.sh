#!/bin/bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd -P)"
asset="codex-clawd-status-macos-arm64.tar.gz"

"$root/scripts/build-local.sh"
rm -rf "$root/dist/release"
mkdir -p "$root/dist/release"
tar -czf "$root/dist/release/$asset" -C "$root/dist" payload
(
  cd "$root/dist/release"
  shasum -a 256 "$asset" > "$asset.sha256"
)
