from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from ..errors import InputError, ExecutionError
from ..schemas import DesignPayload, DesignResponse, DesignMetadata
from .io import (
    make_workspace,
    normalize_chains,
    parse_multiple_chains,
    infer_chains_from_parsed_jsonl,
    assign_fixed_chains,
    run_proteinmpnn,
    rename_first_fasta_to_result,
    parse_outputs,
)


def run_design(
    *,
    job_dir: Path,
    structure_path: Path,
    original_filename: str,
    payload: DesignPayload,
    proteinmpnn_dir: Optional[Path] = None,
    timeout_sec: Optional[int] = None,
    seed: int = 0,
) -> DesignResponse:
    """Run ProteinMPNN design and write artifacts under job_dir/.

    Artifact contract (under job_dir/):
      input/<original_filename>
      input/<stem>.pdb
      output/run.log
      output/parsed_pdbs.jsonl
      output/chain_id.jsonl (always; inferred chains when payload.chains omitted)
      output/seqs/<stem>_res.fa
      output/response.json
    """
    pm_dir = proteinmpnn_dir or Path(os.getenv("PROTEIN_MPNN_DIR", "/opt/ProteinMPNN"))
    to_sec = int(timeout_sec or os.getenv("MPNN_TIMEOUT_SEC", "600"))

    # 0) normalize workspace + ensure input pdb for parsing
    ws = make_workspace(job_dir=job_dir, structure_path=structure_path, original_filename=original_filename)

    # 1) parse_multiple_chains -> output/parsed_pdbs.jsonl
    parsed_jsonl = ws.output_dir / "parsed_pdbs.jsonl"
    parse_multiple_chains(
        proteinmpnn_dir=pm_dir,
        input_dir=ws.input_dir,
        parsed_jsonl=parsed_jsonl,
        log_path=ws.log_path,
        timeout_sec=to_sec,
    )

    # 2) chain list:
    #    - if user provided chains: use them
    #    - else: infer all chains (but still record "all chains" semantics by leaving ws-chains empty downstream)
    user_chains = normalize_chains(payload.chains)
    chain_list_for_jsonl = user_chains or infer_chains_from_parsed_jsonl(parsed_jsonl)
    if not chain_list_for_jsonl:
        raise ExecutionError(
            "Could not infer chains from parsed_pdbs.jsonl",
            returncode=1,
            stdout="",
            stderr="parsed_pdbs.jsonl did not contain seq_chain_* keys",
        )

    # 3) assign_fixed_chains -> output/chain_id.jsonl (always)
    chain_id_jsonl = ws.output_dir / "chain_id.jsonl"
    assign_fixed_chains(
        proteinmpnn_dir=pm_dir,
        parsed_jsonl=parsed_jsonl,
        chain_list=chain_list_for_jsonl,
        chain_id_jsonl=chain_id_jsonl,
        log_path=ws.log_path,
        timeout_sec=to_sec,
    )

    # 4) run ProteinMPNN
    runtime_ms = run_proteinmpnn(
        proteinmpnn_dir=pm_dir,
        jsonl_path=parsed_jsonl,
        chain_id_jsonl=chain_id_jsonl,
        out_folder=ws.output_dir,
        num_sequences=payload.num_sequences,
        model_name=payload.model_name,
        seed=seed,
        log_path=ws.log_path,
        timeout_sec=to_sec,
    )

    # 5) Standardize output FASTA name: <stem>_res.fa
    rename_first_fasta_to_result(ws.seqs_dir, stem=ws.uploaded_path.stem or "input")

    # 6) Build response (empty user_chains => return all chains)
    original, designed = parse_outputs(ws.output_dir, chains_requested=user_chains)
    resp = DesignResponse(
        metadata=DesignMetadata(model_version=payload.model_name, runtime_ms=runtime_ms, seed=seed),
        designed_sequences=designed,
        original_sequences=original,
    )

    # 7) Persist canonical response artifact
    (ws.output_dir / "response.json").write_text(json.dumps(resp.model_dump(), indent=2), encoding="utf-8")
    return resp
