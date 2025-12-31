#!/usr/bin/env bash
set -euo pipefail

curl -sS -X POST http://localhost:8000/design \
  -F structure=@examples/tiny.pdb \
  -F chains=A \
  -F num_sequences=5 | python -m json.tool
