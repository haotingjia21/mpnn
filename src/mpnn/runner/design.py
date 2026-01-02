from __future__ import annotations

import json
import os
from pathlib import Path

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
from .metadata import canonical_jsonl_sha256, collect_versions, get_repo_git_sha, sha256_file, write_checksums, write_json


def _resolve_model_args(payload: DesignPayload, defaults: AppConfig.ModelDefaults) -> AppConfig.ModelDefaults:
    """Merge per-request overrides onto deployment defaults."""

    overrides = payload.model_dump(exclude_none=True)
    overrides.pop("chains", None)
    merged = {**defaults.model_dump(), **overrides}
    return AppConfig.ModelDefaults.model_validate(merged)


def _mock_write_artifacts(*, ws, model_args: AppConfig.ModelDefaults, seed: int) -> int:
    """Create deterministic dummy artifacts for tests (MPNN_MOCK=1)."""

    # Minimal log
    ws.log_path.write_text("mock run\n", encoding="utf-8")

    base = ws.normalized_pdb.stem

    # Pretend we parsed two chains (A,B)
    parsed_jsonl = ws.artifacts_dir / "parsed_pdbs.jsonl"
    parsed_jsonl.write_text(
        json.dumps(
            {
                "name": base,
                "num_of_chains": 2,
                "seq_chain_A": "AAAA",
                "seq_chain_B": "BBBB",
                "seq": "AAAA/BBBB",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Pretend we assigned fixed chains
    chain_ids_jsonl = ws.artifacts_dir / "chain_ids.jsonl"
    chain_ids_jsonl.write_text(json.dumps({base: [["A", "B"], []]}) + "\n", encoding="utf-8")

    # Create dummy FASTA outputs: record0=original, then N designed samples.
    seqs_dir = ws.model_outputs_dir / "seqs"
    seqs_dir.mkdir(parents=True, exist_ok=True)

    # Match ProteinMPNN header style enough for metadata extraction.
    mock_git = "0" * 40
    lines = [
        f">{base}, score=1.0, global_score=1.0, fixed_chains=[], designed_chains=['A'], "
        f"model_name={model_args.model_name}, git_hash={mock_git}, seed={seed}\n",
        "AAAA/BBBB\n",
    ]
    for i in range(1, model_args.num_seq_per_target + 1):
        # Designed sequences change with i so ranks are non-identical
        a = "AAA" + chr(ord("C") + (i % 20))
        b = "BBB" + chr(ord("D") + (i % 20))
        lines.append(f">sample={i}\n")
        lines.append(f"{a}/{b}\n")

    # Write the file with a non-standard name then rename to *_res.fa like real pipeline
    tmp_fa = seqs_dir / f"{base}.fa"
    tmp_fa.write_text("".join(lines), encoding="utf-8")
    rename_first_fasta_to_result(seqs_dir, stem=base)

    # Runtime
    return 1


def run_design(
    *,
    job_dir: Path,
    structure_path: Path,
    original_filename: str,
    payload: DesignPayload,
    model_defaults: AppConfig.ModelDefaults,
    proteinmpnn_dir: Path = Path("/opt/ProteinMPNN"),
    timeout_sec: int = 600,
    mock: bool = False,
    seed: int = 0,
) -> DesignResponse:
    """Run ProteinMPNN design and write artifacts under job_dir/.

    Artifact contract (under job_dir/):

        runs/jobs/<id>/
          inputs/
            <original_uploaded_filename>
            manifest.json
          artifacts/
            <base_name>.pdb
            parsed_pdbs.jsonl
            chain_ids.jsonl
          logs/
            run.log
          model_outputs/
            seqs/
              <base_name>_res.fa
          formatted_outputs/
          responses/
            response.json
          metadata/
            checksums.sha256
            versions.json
    """

    pm_dir = proteinmpnn_dir
    to_sec = timeout_sec

    # Resolve model arguments (defaults from config.json, request overrides optional)
    model_args = _resolve_model_args(payload, model_defaults)

    # 0) workspace + normalize input structure into artifacts/<base>.pdb
    ws = make_workspace(job_dir=job_dir, structure_path=structure_path, original_filename=original_filename)

    base_name = ws.normalized_pdb.stem

    # 1..5) pipeline (real or mock)
    if mock:
        runtime_ms = _mock_write_artifacts(ws=ws, model_args=model_args, seed=seed)
    else:
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
            num_seq_per_target=model_args.num_seq_per_target,
            sampling_temp=model_args.sampling_temp,
            batch_size=model_args.batch_size,
            model_name=model_args.model_name,
            seed=seed,
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
        metadata=DesignMetadata(model_version=model_args.model_name, runtime_ms=runtime_ms, seed=seed),
        designed_sequences=designed,
        original_sequences=original,
    )

    # 7) Persist API response artifact
    write_json(ws.responses_dir / "response.json", resp.model_dump())

    # 8) Metadata: manifest + versions + checksums
    raw_input_sha256 = sha256_file(ws.uploaded_path)
    canonical_preprocess_sha256 = canonical_jsonl_sha256(parsed_jsonl) if parsed_jsonl.exists() else None

    # model_git_sha comes from the ProteinMPNN git repo inside the container.
    model_git_sha = ("0" * 40) if mock else get_repo_git_sha(pm_dir)

    # container image must be provided by the runtime (e.g., docker compose / k8s manifest).
    container_image = os.getenv("CONTAINER_IMAGE")
    if not container_image:
        raise RuntimeError(
            "Missing required env var CONTAINER_IMAGE. Set it in docker compose or with -e CONTAINER_IMAGE=<image>."
        )

    versions = collect_versions(model_name=model_args.model_name, model_git_sha=model_git_sha, container_image=container_image)
    write_json(ws.metadata_dir / "versions.json", versions)

    request_payload = payload.model_dump(exclude_none=True, by_alias=True)
    effective_payload = {
        **({"chains": payload.chains} if payload.chains is not None else {}),
        **model_args.model_dump(),
    }

    manifest = {
        "original_filename": ws.uploaded_path.name,
        "request": request_payload,
        "effective": effective_payload,
        "seed": seed,
        "checksums": {
            "input_sha256": raw_input_sha256,
            "canonical_preprocess_sha256": canonical_preprocess_sha256,
        },
        "versions": {
            "model_git_sha": versions.get("model_git_sha"),
            "model_name": model_args.model_name,
            "container_image": versions.get("container_image"),
        },
        "defaults": {"model_defaults": model_defaults.model_dump()},
    }
    write_json(ws.inputs_dir / "manifest.json", manifest)

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
        ws.metadata_dir / "versions.json",
    ]
    write_checksums(out_path=ws.metadata_dir / "checksums.sha256", job_dir=ws.job_dir, files=files_to_hash)

    return resp
