#!/bin/bash
set -euo pipefail

repo="kubai087/codex-clawd-status-macos"
asset="codex-clawd-status-macos-arm64.tar.gz"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "clawd-status requires an Apple silicon Mac" >&2
  exit 1
fi

install_payload() {
  local payload="$1"
  "$payload/bin/clawd-status" install --payload "$payload"
}

if [[ "${1:-}" == "--payload" ]]; then
  if [[ -z "${2:-}" || -n "${3:-}" ]]; then
    echo "usage: ./install.sh [--payload PATH]" >&2
    exit 2
  fi
  payload="$(cd "$2" && pwd -P)"
  install_payload "$payload"
  exit $?
fi

if [[ -n "${1:-}" ]]; then
  echo "usage: ./install.sh [--payload PATH]" >&2
  exit 2
fi

base="${CLAWD_STATUS_DOWNLOAD_BASE:-https://github.com/$repo/releases/latest/download}"
temporary="$(mktemp -d "${TMPDIR:-/tmp}/codex-clawd-status.XXXXXX")"
trap 'rm -rf "$temporary"' EXIT

curl -fsSL "$base/$asset" -o "$temporary/$asset"
curl -fsSL "$base/$asset.sha256" -o "$temporary/$asset.sha256"
(
  cd "$temporary"
  shasum -a 256 -c "$asset.sha256"
)

while IFS= read -r member; do
  case "$member" in
    /*|../*|*/../*|*/..)
      echo "unsafe archive path: $member" >&2
      exit 3
      ;;
  esac
done < <(tar -tzf "$temporary/$asset")

tar -xzf "$temporary/$asset" -C "$temporary"
install_payload "$temporary/payload"
