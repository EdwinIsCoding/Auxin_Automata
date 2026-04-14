#!/usr/bin/env bash
# healthcheck.sh — verify the Auxin bridge is live and streaming
#
# Usage:
#   ./scripts/healthcheck.sh [host] [port]
#
# Defaults to localhost:8767.
# Exits 0 on success, 1 on failure.

set -euo pipefail

HOST="${1:-localhost}"
PORT="${2:-8767}"
URL="http://${HOST}:${PORT}/healthz"

echo "Checking bridge health at ${URL} …"

RESPONSE=$(curl -sf --max-time 5 "${URL}") || {
  echo "FAIL: could not reach ${URL}"
  exit 1
}

echo "Response: ${RESPONSE}"

# Verify status == "ok"
STATUS=$(echo "${RESPONSE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))")
if [ "${STATUS}" != "ok" ]; then
  echo "FAIL: bridge status is '${STATUS}', expected 'ok'"
  exit 1
fi

# Verify source_status == "streaming"
SOURCE_STATUS=$(echo "${RESPONSE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('source_status',''))")
if [ "${SOURCE_STATUS}" != "streaming" ]; then
  echo "WARN: source_status is '${SOURCE_STATUS}', expected 'streaming' (bridge may be initialising)"
fi

echo "OK: bridge is healthy (source_status=${SOURCE_STATUS})"
