"""command-line interface for ProteinMPNN design."""

from __future__ import annotations
import argparse
import json
from pathlib import Path

from .core import AppConfig, DesignPayload, load_config
from .runner.design import run_design

def main() -> None:
    p = argparse.ArgumentParser(description="Run ProteinMPNN design.")
    p.add_argument("--structure", required=True, help="Path to structure file (.pdb/.cif)")
    p.add_argument(
        "--payload",
        required=True,
        help="Path to JSON payload (required fields: chains, num_sequences; optional: model_name)",
    )
    p.add_argument("--job_dir", required=True, help="Workspace/job directory (will contain inputs/ and artifacts/model_outputs/responses/metadata/)")
    p.add_argument("--proteinmpnn_dir", default=None, help="Override ProteinMPNN repo path (otherwise from config)")
    p.add_argument("--timeout_sec", type=int, default=None, help="Override timeout seconds (otherwise from config)")

    args = p.parse_args()

    cfg: AppConfig = load_config(Path("config.json"))
    payload_obj = DesignPayload.model_validate(json.loads(Path(args.payload).read_text(encoding="utf-8")))
    resp = run_design(
        job_dir=Path(args.job_dir),
        structure_path=Path(args.structure),
        original_filename=Path(args.structure).name,
        payload=payload_obj,
        model_defaults=cfg.model_defaults,
        proteinmpnn_dir=Path(args.proteinmpnn_dir) if args.proteinmpnn_dir else cfg.proteinmpnn_dir,
        timeout_sec=args.timeout_sec if args.timeout_sec is not None else cfg.timeout_sec,
    )

    print(json.dumps(resp.model_dump(), indent=2))


if __name__ == "__main__":
    main()
