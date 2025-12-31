#!/usr/bin/env bash
set -euo pipefail
HOST="${HOST:-http://localhost:8000}"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <structure.pdb|structure.cif> [chains] [num_sequences]" >&2
  echo 'chains examples: A  B  ["A","B"]  (or empty for none)' >&2
  exit 2
fi

STRUCTURE="$1"
CHAINS="${2:-}"
NSEQ="${3:-5}"

# Spec: JSON + file
PAYLOAD=$(python - <<PY
import json,sys
chains = sys.argv[1]
nseq = int(sys.argv[2])
obj = {"num_sequences": nseq}
if chains.strip():
    try:
        # allow JSON list or plain string
        c = json.loads(chains)
        obj["chains"] = c
    except Exception:
        obj["chains"] = chains
print(json.dumps(obj))
PY
"$CHAINS" "$NSEQ")

curl -sS -X POST "$HOST/design" \
  -F "structure=@${STRUCTURE}" \
  -F "payload=${PAYLOAD}" | python -m json.tool
