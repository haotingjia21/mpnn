from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Union

from .jobs import JobPaths, create_job_dir, write_structure
from .fasta import load_designed_sequences_from_out
from .schemas import DesignMetadata, DesignPayload, DesignedSequence, DesignResponse

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M",
}


# ---------------------------
# Errors
# ---------------------------

class RunnerError(Exception):
    pass


class ProteinMPNNConfigError(RunnerError):
    pass


class ProteinMPNNExecutionError(RunnerError):
    def __init__(self, message: str, *, returncode: int, stdout: str, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------
# Utilities
# ---------------------------

def normalize_chains(chains: Optional[Union[str, List[str]]]) -> List[str]:
    """
    Accept:
      - None / "" -> []
      - "A" / "A,B" / "A B"
      - ["A","B"]
    """
    if chains is None:
        return []
    if isinstance(chains, list):
        return [c.strip() for c in chains if isinstance(c, str) and c.strip()]
    if isinstance(chains, str):
        s = chains.strip()
        if not s:
            return []
        return [p for p in re.split(r"[,\s]+", s) if p]
    return []


def parse_pdb_sequences(pdb_text: str) -> Dict[str, str]:
    """
    Tiny PDB ATOM parser -> chain sequences (1-letter).
    Used for UI diff highlighting and default chain inference.
    """
    seen: Dict[tuple, str] = {}
    order: List[tuple] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or len(line) < 27:
            continue
        resn = line[17:20].strip().upper()
        chain = (line[21].strip() or "A")
        resseq = line[22:26].strip()
        icode = line[26:27].strip()
        key = (chain, resseq, icode)
        if key in seen:
            continue
        seen[key] = AA3_TO_1.get(resn, "X")
        order.append(key)

    out: Dict[str, List[str]] = {}
    for chain, resseq, icode in order:
        out.setdefault(chain, []).append(seen[(chain, resseq, icode)])
    return {c: "".join(v) for c, v in out.items()}


def _diff_positions(a: str, b: str) -> List[int]:
    L = min(len(a), len(b))
    diffs = [i + 1 for i in range(L) if a[i] != b[i]]
    if len(a) != len(b):
        diffs += list(range(L + 1, max(len(a), len(b)) + 1))
    return diffs


def _truncate(s: str, n: int = 4000) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "\n…(truncated)…"


def _resolve_proteinmpnn_script() -> Path:
    """
    Default matches your repo layout:
      software/ProteinMPNN/protein_mpnn_run.py

    Override with:
      PROTEIN_MPNN_SCRIPT=/abs/path/to/protein_mpnn_run.py
    """
    script = os.getenv("PROTEIN_MPNN_SCRIPT", "software/ProteinMPNN/protein_mpnn_run.py")
    p = Path(script)
    if not p.is_file():
        raise ProteinMPNNConfigError(
            f"ProteinMPNN script not found at {p!s}. "
            f"Set PROTEIN_MPNN_SCRIPT or ensure repo has software/ProteinMPNN/protein_mpnn_run.py"
        )
    return p.resolve()


def prepare_job_inputs(
    *, structure_bytes: bytes, filename: str, base_dir: str = "runs/jobs"
) -> tuple[JobPaths, Path]:
    job = create_job_dir(base_dir=base_dir)
    input_path = write_structure(job, structure_bytes, filename)
    return job, input_path


def parse_job_outputs(*, job: JobPaths, chains: List[str]) -> List[DesignedSequence]:
    return load_designed_sequences_from_out(Path(job.out_dir), chains)


# ---------------------------
# Runner contract
# ---------------------------

class ProteinMPNNRunner(Protocol):
    model_version: str

    def design(self, *, structure_bytes: bytes, filename: str, payload: DesignPayload) -> DesignResponse:
        ...


# ---------------------------
# Real runner (subprocess)
# ---------------------------

class RealProteinMPNNRunner:
    def __init__(self) -> None:
        self.script_path = _resolve_proteinmpnn_script()
        self.model_version = os.getenv("MPNN_MODEL_VERSION", "proteinmpnn")
        self.timeout_sec = int(os.getenv("MPNN_TIMEOUT_SEC", "600"))
        self.jobs_dir = os.getenv("MPNN_JOBS_DIR", "runs/jobs")

    def design(self, *, structure_bytes: bytes, filename: str, payload: DesignPayload) -> DesignResponse:
        # For now: assume PDB. If you want CIF, implement conversion before enabling.
        if (filename or "").lower().endswith((".cif", ".mmcif")):
            raise RunnerError("CIF upload not supported in real mode yet. Upload a .pdb (or add CIF->PDB conversion).")

        t0 = time.perf_counter()

        job, input_path = prepare_job_inputs(
            structure_bytes=structure_bytes,
            filename=filename,
            base_dir=self.jobs_dir,
        )

        # Original sequences (UI diff highlighting + default chain inference)
        original = parse_pdb_sequences(structure_bytes.decode("utf-8", errors="ignore"))

        chain_list = normalize_chains(payload.chains)
        # If user didn't specify chains, pass "" to ProteinMPNN (matches your CLI),
        # but for parsing/mapping we can use the original chain IDs if present.
        chains_for_parse = chain_list or (sorted(original.keys()) if original else ["A"])
        chains_arg = ",".join(chain_list) if chain_list else ""

        cmd = [
            sys.executable,
            str(self.script_path),
            "--pdb_path",
            str(input_path),
            "--pdb_path_chains",
            chains_arg,
            "--out_folder",
            str(job.out_dir),
            "--num_seq_per_target",
            str(payload.num_sequences),
        ]

        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired as e:
            raise ProteinMPNNExecutionError(
                f"ProteinMPNN timed out after {self.timeout_sec}s",
                returncode=124,
                stdout=_truncate(getattr(e, "stdout", "") or ""),
                stderr=_truncate(getattr(e, "stderr", "") or ""),
            ) from e

        if proc.returncode != 0:
            raise ProteinMPNNExecutionError(
                "ProteinMPNN failed",
                returncode=proc.returncode,
                stdout=_truncate(proc.stdout or ""),
                stderr=_truncate(proc.stderr or ""),
            )

        designed = parse_job_outputs(job=job, chains=chains_for_parse)

        # Fill diff_positions using original (if chain matches)
        for d in designed:
            orig = original.get(d.chain, "")
            if orig:
                d.diff_positions = _diff_positions(orig, d.sequence)
            else:
                d.diff_positions = []

        runtime_ms = int((time.perf_counter() - t0) * 1000)
        return DesignResponse(
            metadata=DesignMetadata(model_version=self.model_version, runtime_ms=runtime_ms),
            designed_sequences=designed,
            original_sequences=original,
        )


# ---------------------------
# Singleton
# ---------------------------

_RUNNER: Optional[ProteinMPNNRunner] = None


def get_runner() -> ProteinMPNNRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = RealProteinMPNNRunner()
    return _RUNNER
