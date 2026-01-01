from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Protocol, Union

from Bio.PDB import MMCIFParser, PDBIO

from .fasta import load_original_and_designed_from_out
from .jobs import JobPaths, create_job_dir, write_structure
from .schemas import DesignMetadata, DesignPayload, DesignResponse


class RunnerError(Exception):
    pass


class RunnerInputError(RunnerError):
    pass


class ProteinMPNNConfigError(RunnerError):
    pass


class ProteinMPNNExecutionError(RunnerError):
    def __init__(self, message: str, *, returncode: int, stdout: str, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def normalize_chains(chains: Optional[Union[str, List[str]]]) -> List[str]:
    """Accepts "A B", "A,B", or ["A","B"] and returns ["A","B"]."""
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


def _diff_positions(a: str, b: str) -> List[int]:
    """1-indexed positions where sequences differ (including length mismatch)."""
    L = min(len(a), len(b))
    diffs = [i + 1 for i in range(L) if a[i] != b[i]]
    if len(a) != len(b):
        diffs += list(range(L + 1, max(len(a), len(b)) + 1))
    return diffs


def _resolve_proteinmpnn_script() -> Path:
    """Find protein_mpnn_run.py.

    In Docker, set:
      PROTEIN_MPNN_SCRIPT=/opt/ProteinMPNN/protein_mpnn_run.py

    For local dev, we also try a couple common repo-relative fallbacks.
    """
    env = os.getenv("PROTEIN_MPNN_SCRIPT")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
        raise ProteinMPNNConfigError(f"PROTEIN_MPNN_SCRIPT is set but not found: {p}")

    for candidate in [
        Path("vendor/ProteinMPNN/protein_mpnn_run.py"),
        Path("software/ProteinMPNN/protein_mpnn_run.py"),
    ]:
        if candidate.is_file():
            return candidate.resolve()

    raise ProteinMPNNConfigError(
        "protein_mpnn_run.py not found. Set PROTEIN_MPNN_SCRIPT to an absolute path "
        "(e.g., /opt/ProteinMPNN/protein_mpnn_run.py inside Docker)."
    )


def _convert_cif_to_pdb(cif_path: Path, pdb_path: Path) -> None:
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


class ProteinMPNNRunner(Protocol):
    model_version: str

    def design(self, *, structure_bytes: bytes, filename: str, payload: DesignPayload) -> DesignResponse:
        ...


class RealProteinMPNNRunner:
    def __init__(self) -> None:
        self.script_path = _resolve_proteinmpnn_script()
        self.model_version = os.getenv("MPNN_MODEL_VERSION", "proteinmpnn")
        self.timeout_sec = int(os.getenv("MPNN_TIMEOUT_SEC", "600"))
        self.jobs_dir = os.getenv("MPNN_JOBS_DIR", "runs/jobs")

    def design(self, *, structure_bytes: bytes, filename: str, payload: DesignPayload) -> DesignResponse:
        job: JobPaths = create_job_dir(base_dir=self.jobs_dir)
        input_path = write_structure(job, structure_bytes, filename)

        suffix = (input_path.suffix or "").lower()
        if suffix in (".cif", ".mmcif"):
            pdb_path = job.root / "input.pdb"
            _convert_cif_to_pdb(input_path, pdb_path)
        elif suffix == ".pdb":
            pdb_path = input_path
        else:
            raise RunnerInputError("Upload must be .pdb, .cif, or .mmcif")

        chains = normalize_chains(payload.chains)

        cmd = [
            sys.executable,
            str(self.script_path),
            "--pdb_path",
            str(pdb_path),
            "--out_folder",
            str(job.out_dir),
            "--num_seq_per_target",
            str(payload.num_sequences),
        ]
        if chains:
            cmd += ["--pdb_path_chains", " ".join(chains)]

        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
        )
        runtime_ms = int((time.perf_counter() - t0) * 1000)

        if proc.returncode != 0:
            raise ProteinMPNNExecutionError(
                "ProteinMPNN failed",
                returncode=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
            )

        # IMPORTANT: original is FIRST FASTA record
        original, designed = load_original_and_designed_from_out(Path(job.out_dir), chains)

        for d in designed:
            orig = original.get(d.chain, "")
            d.diff_positions = _diff_positions(orig, d.sequence) if orig else []

        return DesignResponse(
            metadata=DesignMetadata(model_version=self.model_version, runtime_ms=runtime_ms),
            designed_sequences=designed,
            original_sequences=original,
        )


_RUNNER: Optional[ProteinMPNNRunner] = None


def get_runner() -> ProteinMPNNRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = RealProteinMPNNRunner()
    return _RUNNER
