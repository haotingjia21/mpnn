from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner.design import run_design
from .schemas import DesignPayload


def main() -> None:
    p = argparse.ArgumentParser(description="Run ProteinMPNN design (Kubeflow/K8s-friendly).")
    p.add_argument("--structure", required=True, help="Path to structure file (.pdb/.cif/.mmcif)")
    p.add_argument("--payload", required=True, help="Path to JSON payload (chains/num_sequences/model_name)")
    p.add_argument("--job_dir", required=True, help="Workspace/job directory (will contain input/ and output/)")
    p.add_argument("--proteinmpnn_dir", default=None, help="Path to cloned ProteinMPNN repo (default: /opt/ProteinMPNN)")
    p.add_argument("--timeout_sec", type=int, default=None, help="Timeout in seconds (default: env MPNN_TIMEOUT_SEC or 600)")
    p.add_argument("--seed", type=int, default=0, help="Random seed (default: 0)")

    args = p.parse_args()

    payload_obj = DesignPayload.model_validate(json.loads(Path(args.payload).read_text(encoding="utf-8")))
    resp = run_design(
        job_dir=Path(args.job_dir),
        structure_path=Path(args.structure),
        original_filename=Path(args.structure).name,
        payload=payload_obj,
        proteinmpnn_dir=Path(args.proteinmpnn_dir) if args.proteinmpnn_dir else None,
        timeout_sec=args.timeout_sec,
        seed=args.seed,
    )

    print(json.dumps(resp.model_dump(), indent=2))


if __name__ == "__main__":
    main()
