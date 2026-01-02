#!/usr/bin/env python3
"""
Minimal client for the mpnn service.

Examples:
  python scripts/client.py health
  python scripts/client.py design examples/toy.pdb --chains A --nseq 5 --model v_48_020

Env:
  MPNN_HOST (default: http://localhost:8000)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import requests


def host(h: str | None) -> str:
    h = (h or os.getenv("MPNN_HOST") or "http://localhost:8000").rstrip("/")
    return h if h.startswith(("http://", "https://")) else "http://" + h


def jprint(x) -> None:
    print(json.dumps(x, indent=2))


def cmd_health(args) -> int:
    r = requests.get(host(args.host) + "/health", timeout=args.timeout)
    if r.ok:
        jprint(r.json())
        return 0
    print(f"HTTP {r.status_code}\n{r.text}")
    return 1


def cmd_design(args) -> int:
    payload = {"num_sequences": int(args.nseq), "model_name": args.model}
    if (args.chains or "").strip():
        payload["chains"] = args.chains

    p = Path(args.structure)
    with p.open("rb") as f:
        r = requests.post(
            host(args.host) + "/design",
            files={"structure": (p.name, f, "application/octet-stream")},
            data={"payload": json.dumps(payload)},
            timeout=args.timeout,
        )

    if r.ok:
        jprint(r.json())
        return 0

    print(f"HTTP {r.status_code}")
    try:
        jprint(r.json())
    except Exception:
        print(r.text)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser("mpnn client")
    ap.add_argument("--host", default=None)
    ap.add_argument("--timeout", type=int, default=600)

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("health")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("design")
    p.add_argument("structure")
    p.add_argument("--chains", default="A")  # empty => all chains
    p.add_argument("--nseq", type=int, default=5)
    p.add_argument("--model", default="v_48_020")
    p.set_defaults(func=cmd_design)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
