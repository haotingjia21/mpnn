from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from Bio import SeqIO
from Bio.PDB import MMCIFParser, PDBIO

from ..core import DesignedSequence, ExecutionError, InputError


@dataclass(frozen=True)
class Workspace:
    """Filesystem layout for a single design job."""

    job_dir: Path

    # Top-level folders
    inputs_dir: Path
    artifacts_dir: Path
    logs_dir: Path
    model_outputs_dir: Path
    formatted_outputs_dir: Path
    responses_dir: Path
    metadata_dir: Path

    # Common files
    log_path: Path  # logs/run.log
    uploaded_path: Path  # inputs/<original_filename>
    normalized_pdb: Path  # artifacts/<base_name>.pdb (original or converted)


# ----------------------------
# Generic helpers
# ----------------------------


def convert_cif_to_pdb(cif_path: Path, pdb_path: Path) -> None:
    parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure("cif", str(cif_path))

    # Minimal PDB compatibility: truncate chain IDs to 1 char.
    models = list(structure)
    if models:
        for chain in models[0]:
            cid = str(chain.id) if chain.id is not None else "A"
            chain.id = (cid.strip()[:1] or "A")

    io = PDBIO()
    io.set_structure(structure)
    io.save(str(pdb_path))


def run_cmd(cmd: List[str], *, timeout_sec: int) -> Tuple[int, str, str, int]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    runtime_ms = int((time.perf_counter() - t0) * 1000)
    return proc.returncode, (proc.stdout or ""), (proc.stderr or ""), runtime_ms


def append_log(
    log_path: Path,
    *,
    title: str,
    cmd: List[str],
    rc: int,
    out: str,
    err: str,
    runtime_ms: int,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"\n===== {title} =====\n")
        f.write("cmd: " + " ".join(cmd) + "\n")
        f.write(f"returncode: {rc}\n")
        f.write(f"runtime_ms: {runtime_ms}\n")
        f.write("\n---- stdout ----\n")
        f.write(out.rstrip("\n") + "\n")
        f.write("\n---- stderr ----\n")
        f.write(err.rstrip("\n") + "\n")


def normalize_chains(chains: Optional[object]) -> List[str]:
    """Normalize chain input.

    HW spec allows: "A" or ["A","B"].
    UI provides: "A B" or "A,B". We also strip accidental quotes.
    """

    if chains is None:
        return []

    def clean(tok: str) -> str:
        return tok.strip().strip("\"'").strip()

    items: List[str] = []
    if isinstance(chains, list):
        for c in chains:
            if isinstance(c, str):
                cc = clean(c)
                if cc:
                    items.append(cc)
    elif isinstance(chains, str):
        s = chains.strip()
        if not s:
            return []
        if s.upper() == "ALL":
            return []
        for p in re.split(r"[,\s]+", s):
            if p:
                cp = clean(p)
                if cp:
                    items.append(cp)
    else:
        return []

    out: List[str] = []
    for c in items:
        if c not in out:
            out.append(c)
    return out


# ----------------------------
# Workspace / input normalization
# ----------------------------


def make_workspace(*, job_dir: Path, structure_path: Path, original_filename: str) -> Workspace:
    """Create job workspace folders and normalize uploaded structure.

    Layout:
      inputs/     raw uploads + manifest.json
      artifacts/  derived/normalized structure + jsonl files
      logs/       run.log
      model_outputs/seqs  ProteinMPNN outputs
      responses/        response.json
      metadata/   checksums.sha256, run_metadata.json
    """

    job_dir.mkdir(parents=True, exist_ok=True)

    inputs_dir = job_dir / "inputs"
    artifacts_dir = job_dir / "artifacts"
    logs_dir = job_dir / "logs"
    model_outputs_dir = job_dir / "model_outputs"
    formatted_outputs_dir = job_dir / "formatted_outputs"
    responses_dir = job_dir / "responses"
    metadata_dir = job_dir / "metadata"

    # Create folders
    for p in [inputs_dir, artifacts_dir, logs_dir, model_outputs_dir, formatted_outputs_dir, responses_dir, metadata_dir]:
        p.mkdir(parents=True, exist_ok=True)
    (model_outputs_dir / "seqs").mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / "run.log"

    # Record raw upload under inputs/
    uploaded_name = Path(original_filename or structure_path.name or "input.pdb").name
    uploaded_path = inputs_dir / uploaded_name

    if structure_path.resolve() != uploaded_path.resolve():
        shutil.copyfile(structure_path, uploaded_path)

    # Create normalized PDB under artifacts/
    n = uploaded_path.name.lower()
    stem = uploaded_path.stem or "input"
    normalized_pdb = artifacts_dir / f"{stem}.pdb"

    if n.endswith(".pdb"):
        if uploaded_path.resolve() != normalized_pdb.resolve():
            shutil.copyfile(uploaded_path, normalized_pdb)
    elif n.endswith(".cif") or n.endswith(".mmcif"):
        convert_cif_to_pdb(uploaded_path, normalized_pdb)
    else:
        raise InputError("Upload must be .pdb, .cif, or .mmcif")

    return Workspace(
        job_dir=job_dir,
        inputs_dir=inputs_dir,
        artifacts_dir=artifacts_dir,
        logs_dir=logs_dir,
        model_outputs_dir=model_outputs_dir,
        formatted_outputs_dir=formatted_outputs_dir,
        responses_dir=responses_dir,
        metadata_dir=metadata_dir,
        log_path=log_path,
        uploaded_path=uploaded_path,
        normalized_pdb=normalized_pdb,
    )


# ----------------------------
# ProteinMPNN helper scripts (JSONL workflow)
# ----------------------------


def parse_multiple_chains(*, proteinmpnn_dir: Path, input_dir: Path, parsed_jsonl: Path, log_path: Path, timeout_sec: int) -> None:
    helper = proteinmpnn_dir / "helper_scripts" / "parse_multiple_chains.py"
    cmd = [
        sys.executable,
        str(helper),
        "--input_path",
        str(input_dir),
        "--output_path",
        str(parsed_jsonl),
    ]
    rc, out, err, ms = run_cmd(cmd, timeout_sec=timeout_sec)
    append_log(log_path, title="parse_multiple_chains", cmd=cmd, rc=rc, out=out, err=err, runtime_ms=ms)
    if rc != 0:
        raise ExecutionError("parse_multiple_chains.py failed", returncode=rc, stdout=out, stderr=err)


def infer_chains_from_parsed_jsonl(parsed_jsonl: Path) -> List[str]:
    """Infer chain IDs from first jsonl record keys like seq_chain_A."""

    if not parsed_jsonl.exists():
        return []

    # Fail fast if the helper produced malformed JSON.
    line0 = next((ln for ln in parsed_jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()), "")
    if not line0:
        return []
    obj = json.loads(line0)

    chains: List[str] = []
    for k in obj.keys():
        if k.startswith("seq_chain_"):
            cid = k[len("seq_chain_") :]
            if cid and cid not in chains:
                chains.append(cid)
    return sorted(chains)


def assign_fixed_chains(
    *,
    proteinmpnn_dir: Path,
    parsed_jsonl: Path,
    chain_list: List[str],
    chain_id_jsonl: Path,
    log_path: Path,
    timeout_sec: int,
) -> None:
    helper = proteinmpnn_dir / "helper_scripts" / "assign_fixed_chains.py"
    cmd = [
        sys.executable,
        str(helper),
        "--input_path",
        str(parsed_jsonl),
        "--output_path",
        str(chain_id_jsonl),
        "--chain_list",
        " ".join(chain_list),
    ]
    rc, out, err, ms = run_cmd(cmd, timeout_sec=timeout_sec)
    append_log(log_path, title="assign_fixed_chains", cmd=cmd, rc=rc, out=out, err=err, runtime_ms=ms)
    if rc != 0:
        raise ExecutionError("assign_fixed_chains.py failed", returncode=rc, stdout=out, stderr=err)


def run_proteinmpnn(
    *,
    proteinmpnn_dir: Path,
    jsonl_path: Path,
    chain_id_jsonl: Path,
    out_folder: Path,
    num_seq_per_target: int,
    sampling_temp: str,
    batch_size: int,
    model_name: str,
    seed: int,
    log_path: Path,
    timeout_sec: int,
) -> int:
    mpnn = proteinmpnn_dir / "protein_mpnn_run.py"
    cmd = [
        sys.executable,
        str(mpnn),
        "--jsonl_path",
        str(jsonl_path),
        "--chain_id_jsonl",
        str(chain_id_jsonl),
        "--out_folder",
        str(out_folder),
        "--num_seq_per_target",
        str(num_seq_per_target),
        "--sampling_temp",
        str(sampling_temp),
        "--batch_size",
        str(batch_size),
        "--seed",
        str(seed),
        "--model_name",
        str(model_name),
    ]
    rc, out, err, ms = run_cmd(cmd, timeout_sec=timeout_sec)
    append_log(log_path, title="protein_mpnn_run", cmd=cmd, rc=rc, out=out, err=err, runtime_ms=ms)
    if rc != 0:
        raise ExecutionError("ProteinMPNN failed", returncode=rc, stdout=out, stderr=err)
    return ms


# ----------------------------
# Outputs
# ----------------------------


def rename_first_fasta_to_result(seqs_dir: Path, *, stem: str) -> Path | None:
    """Rename first produced fasta to <stem>_res.fa. Returns new path or None."""

    seqs_dir.mkdir(parents=True, exist_ok=True)

    cands = sorted(list(seqs_dir.glob("*.fa")) + list(seqs_dir.glob("*.fasta")))
    cands = [p for p in cands if not p.name.endswith("_res.fa") and not p.name.endswith("_res.fasta")]
    if not cands:
        return None

    src = cands[0]
    dst = seqs_dir / f"{stem}_res.fa"
    if dst.exists():
        dst.unlink()
    src.rename(dst)
    return dst


def _split_multichain_sequence(seq: str, chains: List[str]) -> List[str]:
    if len(chains) <= 1:
        return [seq]
    for sep in ["/", ":", "|", ","]:
        if sep in seq:
            parts = [p.strip() for p in seq.split(sep) if p.strip()]
            if len(parts) == len(chains):
                return parts
    return [seq]


def parse_outputs(
    *,
    res_fa: Path,
    parsed_jsonl: Path,
    chains_requested: List[str],
) -> Tuple[Dict[str, str], List[DesignedSequence]]:
    """Parse ProteinMPNN FASTA outputs.

    Convention:
      - record[0] = original
      - record[1:] = designed

    If chains_requested is empty, return all chains.
    """

    if not res_fa.exists():
        raise FileNotFoundError(f"Missing FASTA output: {res_fa}")

    all_chains = infer_chains_from_parsed_jsonl(parsed_jsonl) or (chains_requested or ["A"])
    design_all = len(chains_requested) == 0
    requested = set(chains_requested)

    records = list(SeqIO.parse(str(res_fa), "fasta"))
    if not records:
        return {}, []

    original_by_chain: Dict[str, str] = {}
    designed: List[DesignedSequence] = []

    orig_seq = str(records[0].seq)
    orig_parts = _split_multichain_sequence(orig_seq, all_chains)
    if len(orig_parts) == len(all_chains):
        for c, part in zip(all_chains, orig_parts):
            original_by_chain[c] = part
    else:
        original_by_chain[",".join(all_chains)] = orig_seq

    rank = 1
    for rec in records[1:]:
        seq = str(rec.seq)
        parts = _split_multichain_sequence(seq, all_chains)

        if len(parts) == len(all_chains):
            for c, part in zip(all_chains, parts):
                if design_all or c in requested:
                    designed.append(DesignedSequence(chain=c, rank=rank, sequence=part))
        else:
            chain_label = ",".join(all_chains)
            designed.append(DesignedSequence(chain=chain_label, rank=rank, sequence=seq))

        rank += 1

    return original_by_chain, designed
