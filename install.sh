#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "clawd-status requires an Apple silicon Mac" >&2
  exit 1
fi

if [[ "${1:-}" != "--payload" || -z "${2:-}" || -n "${3:-}" ]]; then
  echo "usage: ./install.sh --payload PATH" >&2
  exit 2
fi

payload="$(cd "$2" && pwd -P)"
exec "$payload/bin/clawd-status" install --payload "$payload"
