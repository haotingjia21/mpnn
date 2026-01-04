from __future__ import annotations

import os
from pathlib import Path

from importlib.metadata import PackageNotFoundError, version as pkg_version

from pydantic import BaseModel, Field

from ..core import AppConfig, DesignMetadata, DesignPayload, DesignResponse, ExecutionError
from .io import (
    assign_fixed_chains,
    infer_chains_from_parsed_jsonl,
    make_workspace,
    normalize_chains,
    parse_multiple_chains,
    parse_outputs,
    rename_first_fasta_to_result,
    run_proteinmpnn,
)
from .metadata import collect_versions, get_repo_git_sha, sha256_file, write_checksums, write_json


class _ResolvedModelArgs(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_name: str
    sampling_temp: str
    batch_size: int
    num_sequences: int
    seed: int


def _resolve_model_args(payload: DesignPayload, defaults: AppConfig.ModelDefaults) -> _ResolvedModelArgs:
    return _ResolvedModelArgs(
        # Only model_name can be overridden by request. Other model execution
        # parameters must come from config.json.
        model_name=(payload.model_name or defaults.model_name),
        sampling_temp=defaults.sampling_temp,
        batch_size=defaults.batch_size,
        num_sequences=payload.num_sequences,
        seed=defaults.seed,
    )


def run_design(
    *,
    job_dir: Path,
    structure_path: Path,
    original_filename: str,
    payload: DesignPayload,
    model_defaults: AppConfig.ModelDefaults,
    proteinmpnn_dir: Path,
    timeout_sec: int,
) -> DesignResponse:
    """Run a ProteinMPNN design job."""

    pm_dir = proteinmpnn_dir
    to_sec = timeout_sec

    model_args = _resolve_model_args(payload, model_defaults)

    # 0) workspace + normalize input structure
    ws = make_workspace(job_dir=job_dir, structure_path=structure_path, original_filename=original_filename)

    base_name = ws.normalized_pdb.stem

    # 1..5) pipeline
    parsed_jsonl = ws.artifacts_dir / "parsed_pdbs.jsonl"
    parse_multiple_chains(
        proteinmpnn_dir=pm_dir,
        input_dir=ws.artifacts_dir,
        parsed_jsonl=parsed_jsonl,
        log_path=ws.log_path,
        timeout_sec=to_sec,
    )

    user_chains = normalize_chains(payload.chains)
    chain_list_for_jsonl = user_chains or infer_chains_from_parsed_jsonl(parsed_jsonl)
    if not chain_list_for_jsonl:
        raise ExecutionError(
            "Could not infer chains from parsed_pdbs.jsonl",
            returncode=1,
            stdout="",
            stderr="parsed_pdbs.jsonl did not contain seq_chain_* keys",
        )

    chain_ids_jsonl = ws.artifacts_dir / "chain_ids.jsonl"
    assign_fixed_chains(
        proteinmpnn_dir=pm_dir,
        parsed_jsonl=parsed_jsonl,
        chain_list=chain_list_for_jsonl,
        chain_id_jsonl=chain_ids_jsonl,
        log_path=ws.log_path,
        timeout_sec=to_sec,
    )

    runtime_ms = run_proteinmpnn(
        proteinmpnn_dir=pm_dir,
        jsonl_path=parsed_jsonl,
        chain_id_jsonl=chain_ids_jsonl,
        out_folder=ws.model_outputs_dir,
        num_sequences=model_args.num_sequences,
        sampling_temp=model_args.sampling_temp,
        batch_size=model_args.batch_size,
        model_name=model_args.model_name,
        seed=model_args.seed,
        log_path=ws.log_path,
        timeout_sec=to_sec,
    )

    rename_first_fasta_to_result(ws.model_outputs_dir / "seqs", stem=base_name)

    # 6) Build response
    user_chains = normalize_chains(payload.chains)
    parsed_jsonl = ws.artifacts_dir / "parsed_pdbs.jsonl"
    res_fa = (ws.model_outputs_dir / "seqs") / f"{base_name}_res.fa"
    original, designed = parse_outputs(
        res_fa=res_fa,
        parsed_jsonl=parsed_jsonl,
        chains_requested=user_chains,
    )

    resp = DesignResponse(
        metadata=DesignMetadata(model_version=model_args.model_name, runtime_ms=runtime_ms),
        designed_sequences=designed,
        original_sequences=original,
    )

    # 7) Persist API response artifact
    write_json(ws.responses_dir / "response.json", resp.model_dump())

    # 8) Metadata: manifest + versions + checksums
    raw_input_sha256 = sha256_file(ws.uploaded_path)

    # model_git_sha comes from the ProteinMPNN git repo inside the container.
    model_git_sha = get_repo_git_sha(pm_dir)

    # container image must be provided by the runtime (e.g., docker compose / k8s manifest).
    container_image = os.getenv("CONTAINER_IMAGE")
    if not container_image:
        raise RuntimeError(
            "Missing required env var CONTAINER_IMAGE. Set it in docker compose or with -e CONTAINER_IMAGE=<image>."
        )

    versions = collect_versions(
        model_name=model_args.model_name,
        model_git_sha=model_git_sha,
        container_image=container_image,
    )
    app_version = (versions.get("app") or {}).get("version", "")

    # inputs/manifest.json is intended to be an immutable snapshot of *inputs only*.
    request_payload = payload.model_dump(by_alias=True)
    manifest = {
        "original_filename": ws.uploaded_path.name,
        "request": request_payload,
        "checksums": {"input_sha256": raw_input_sha256},
    }
    write_json(ws.inputs_dir / "manifest.json", manifest)

    # metadata/run_metadata.json captures run-time resolved settings + provenance.
    run_metadata = {
        "effective": {
            "chains": payload.chains,
            **model_args.model_dump(),
        },
        "runtime_ms": runtime_ms,
        "checksums": {
            "input_sha256": raw_input_sha256,
        },
        "versions": {
            "app_version": app_version,
            "model_git_sha": versions.get("model_git_sha"),
            "model_name": model_args.model_name,
            "container_image": versions.get("container_image"),
        },
    }
    write_json(ws.metadata_dir / "run_metadata.json", run_metadata)

    # checksums.sha256 lists key artifacts for integrity/audit
    # already resolved above

    files_to_hash = [
        ws.uploaded_path,
        ws.inputs_dir / "manifest.json",
        ws.normalized_pdb,
        ws.artifacts_dir / "parsed_pdbs.jsonl",
        ws.artifacts_dir / "chain_ids.jsonl",
        res_fa,
        ws.responses_dir / "response.json",
        ws.metadata_dir / "run_metadata.json",
    ]
    write_checksums(out_path=ws.metadata_dir / "checksums.sha256", job_dir=ws.job_dir, files=files_to_hash)

    return resp
