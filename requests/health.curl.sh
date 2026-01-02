#!/usr/bin/env bash
set -euo pipefail
HOST="${HOST:-http://localhost:8000}"
curl -sS "$HOST/health"
echo
