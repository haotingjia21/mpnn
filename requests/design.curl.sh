#!/usr/bin/env bash
set -euo pipefail
HOST="${HOST:-http://localhost:8000}"

STRUCTURE="$1"
PAYLOAD_JSON="$2"

curl -sS -X POST "$HOST/design" \
  -F "structure=@${STRUCTURE}" \
  -F "payload=$(cat ${PAYLOAD_JSON})"
echo
