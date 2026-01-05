#!/usr/bin/env python3
"""sample requests to the MPNN REST API service"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import requests

HOST = "http://localhost:8000"

def cfg_defaults() -> tuple[int, str]:
    cfg = Path(__file__).resolve().parents[1] / "config.json"
    d = json.loads(cfg.read_text(encoding="utf-8"))["model_defaults"]
    return int(d["num_sequences"]), str(d["model_name"])

def main() -> int:
    ap = argparse.ArgumentParser("mpnn client")
    ap.add_argument("--host", default=None)
    ap.add_argument("--timeout", type=int, default=600)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    p = sub.add_parser("design")
    p.add_argument("structure")
    p.add_argument("--chains", default=None)  # "" => all-chains
    p.add_argument("--nseq", type=int, default=None)
    p.add_argument("--model", default=None)
    a = ap.parse_args()

    if a.cmd == "health":
        r = requests.get(HOST + "/health", timeout=a.timeout)
        print(r.text)
        return 0 if r.ok else 1

    def_nseq, def_model = cfg_defaults()
    payload = {
        "chains": ((a.chains or "").strip()),
        "num_sequences": int(a.nseq or def_nseq),
        "model_name": str(a.model or def_model),
    }

    path = Path(a.structure)
    with path.open("rb") as f:
        r = requests.post(
            HOST + "/design",
            files={"structure": (path.name, f, "application/octet-stream")},
            data={"payload": json.dumps(payload)},
            timeout=a.timeout,
        )
    print(json.dumps(r.json(), indent=2))
    return 0 if r.ok else 1

if __name__ == "__main__":
    raise SystemExit(main())