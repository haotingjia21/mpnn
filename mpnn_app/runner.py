from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
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


class RunnerError(Exception):
    pass


class RunnerInputError(RunnerError):
    """Client/input error -> API should respond 4xx."""
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


def _resolve_proteinmpnn_script() -> Path:
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_run_log(
    *,
    job: JobPaths,
    cmd: List[str],
    start_utc: str,
    end_utc: str,
    runtime_ms: int,
    returncode: Optional[int],
    stdout: str,
    stderr: str,
) -> None:
    """
    Writes:
      runs/jobs/<id>/run.log
      runs/jobs/<id>/out/seqs/run.log  (copy)
    """
    lines: List[str] = []
    lines.append(f"job_id: {job.job_id}")
    lines.append(f"start_utc: {start_utc}")
    lines.append(f"end_utc: {end_utc}")
    lines.append(f"runtime_ms: {runtime_ms}")
    lines.append(f"returncode: {returncode}")
    lines.append("cmd:")
    lines.append("  " + " ".join(cmd))
    lines.append("")
    lines.append("----- stdout -----")
    lines.append(stdout or "")
    lines.append("")
    lines.append("----- stderr -----")
    lines.append(stderr or "")
    content = "\n".join(lines) + "\n"

    job.log_path.write_text(content, encoding="utf-8", errors="ignore")

    # Also copy into seqs/ for convenience (best-effort)
    try:
        job.seqs_dir.mkdir(parents=True, exist_ok=True)
        (job.seqs_dir / "run.log").write_text(content, encoding="utf-8", errors="ignore")
    except Exception:
        pass


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
        if (filename or "").lower().endswith((".cif", ".mmcif")):
            raise RunnerInputError("CIF upload not supported yet. Upload a .pdb (or implement CIF->PDB conversion).")

        start_utc = _utc_now()
        t0 = time.perf_counter()

        job, input_path = prepare_job_inputs(
            structure_bytes=structure_bytes,
            filename=filename,
            base_dir=self.jobs_dir,
        )

        # Original sequences for UI diff highlighting + default chain inference
        original = parse_pdb_sequences(structure_bytes.decode("utf-8", errors="ignore"))
        available = sorted(original.keys())

        chain_list = normalize_chains(payload.chains)
        if chain_list:
            missing = [c for c in chain_list if c not in original]
            if missing:
                # write a log for failed validation too
                runtime_ms = int((time.perf_counter() - t0) * 1000)
                end_utc = _utc_now()
                _write_run_log(
                    job=job,
                    cmd=[],
                    start_utc=start_utc,
                    end_utc=end_utc,
                    runtime_ms=runtime_ms,
                    returncode=None,
                    stdout="",
                    stderr=f"Requested chains {missing} not found. Available chains: {available}",
                )
                raise RunnerInputError(f"Requested chains {missing} not found. Available chains: {available}")

        chains_for_parse = chain_list or (available if available else ["A"])
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

        proc: Optional[subprocess.CompletedProcess[str]] = None
        stdout = ""
        stderr = ""
        returncode: Optional[int] = None

        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            returncode = proc.returncode

            if proc.returncode != 0:
                runtime_ms = int((time.perf_counter() - t0) * 1000)
                end_utc = _utc_now()
                _write_run_log(
                    job=job,
                    cmd=cmd,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    runtime_ms=runtime_ms,
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
                raise ProteinMPNNExecutionError(
                    "ProteinMPNN failed",
                    returncode=proc.returncode,
                    stdout=stdout,
                    stderr=stderr,
                )

            designed = parse_job_outputs(job=job, chains=chains_for_parse)

            # Fill diff positions
            for d in designed:
                orig = original.get(d.chain, "")
                d.diff_positions = _diff_positions(orig, d.sequence) if orig else []

            runtime_ms = int((time.perf_counter() - t0) * 1000)
            end_utc = _utc_now()

            _write_run_log(
                job=job,
                cmd=cmd,
                start_utc=start_utc,
                end_utc=end_utc,
                runtime_ms=runtime_ms,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )

            return DesignResponse(
                metadata=DesignMetadata(model_version=self.model_version, runtime_ms=runtime_ms),
                designed_sequences=designed,
                original_sequences=original,
            )

        except subprocess.TimeoutExpired as e:
            # capture any partial output
            stdout = getattr(e, "stdout", "") or ""
            stderr = getattr(e, "stderr", "") or ""
            runtime_ms = int((time.perf_counter() - t0) * 1000)
            end_utc = _utc_now()

            _write_run_log(
                job=job,
                cmd=cmd,
                start_utc=start_utc,
                end_utc=end_utc,
                runtime_ms=runtime_ms,
                returncode=124,
                stdout=stdout,
                stderr=stderr or f"Timed out after {self.timeout_sec}s",
            )

            raise ProteinMPNNExecutionError(
                f"ProteinMPNN timed out after {self.timeout_sec}s",
                returncode=124,
                stdout=stdout,
                stderr=stderr,
            ) from e


_RUNNER: Optional[ProteinMPNNRunner] = None


def get_runner() -> ProteinMPNNRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = RealProteinMPNNRunner()
    return _RUNNER
