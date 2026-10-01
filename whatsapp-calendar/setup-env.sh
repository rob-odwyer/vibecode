#!/usr/bin/env bash
# Setup script for a cloud routine environment: builds the whatsmeow bridge.
# Paste its contents into the environment's "Setup script" (or run it from a
# SessionStart hook). Needs: a Go toolchain (any 1.21+, it auto-downloads the
# version go.mod asks for), gcc for the sqlite driver, and access to
# proxy.golang.org.
set -euo pipefail
cd "$(dirname "$0")/bridge"
if [ ! -x wa-bridge ] || [ -n "$(find . -name '*.go' -newer wa-bridge 2>/dev/null)" ]; then
  echo "building wa-bridge..." >&2
  GOTOOLCHAIN=auto go build -o wa-bridge .
fi
./wa-bridge --help >/dev/null 2>&1 || { echo "wa-bridge failed to run" >&2; exit 1; }
echo "wa-bridge ready" >&2
