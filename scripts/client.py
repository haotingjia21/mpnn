#!/usr/bin/env python3
"""
Minimal client for the mpnn service.

Examples:
  python scripts/client.py health
  python scripts/client.py design examples/toy.pdb --chains ALL --nseq 5 --model v_48_020

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
    if h is None:
        h = os.getenv("MPNN_HOST", "http://localhost:8000")
    h = h.rstrip("/")
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
    # Defaults are controlled by repo-root config.json.
    cfg_path = Path(__file__).resolve().parents[1] / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ui_defaults = (cfg.get("ui_defaults") or {})
    model_defaults = (cfg.get("model_defaults") or {})

    # /design requires chains + num_seq_per_target. The client will always send explicit values.
    chains = (args.chains if args.chains is not None else ui_defaults.get("chains") or "ALL").strip() or "ALL"
    nseq = args.nseq if args.nseq is not None else ui_defaults.get("num_seq_per_target")
    model = args.model if args.model is not None else model_defaults.get("model_name")
    if nseq is None or model is None:
        raise SystemExit(
            f"Missing defaults in {cfg_path}. Expected ui_defaults.num_seq_per_target and model_defaults.model_name"
        )

    payload = {"chains": chains, "num_seq_per_target": int(nseq), "model_name": str(model)}

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
    p.add_argument("--chains", default=None)  # use ALL for default all-chains
    p.add_argument("--nseq", type=int, default=None)
    p.add_argument("--model", default=None)
    p.set_defaults(func=cmd_design)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
