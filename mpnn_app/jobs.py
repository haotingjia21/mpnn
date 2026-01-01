from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
import shutil


@dataclass(frozen=True)
class JobPaths:
    job_id: str
    root: Path
    out_dir: Path
    seqs_dir: Path
    log_path: Path


def _safe_ext(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdb"):
        return ".pdb"
    if name.endswith(".cif") or name.endswith(".mmcif"):
        return ".cif"
    # default to pdb
    return ".pdb"


def create_job_dir(base_dir: str | Path = "runs/jobs") -> JobPaths:
    """
    Creates:
      runs/jobs/<uuid>/
        run.log
        out/
          seqs/
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    job_id = uuid4().hex
    root = base / job_id
    root.mkdir(parents=True, exist_ok=False)

    out_dir = root / "out"
    out_dir.mkdir(parents=True, exist_ok=False)

    seqs_dir = out_dir / "seqs"
    seqs_dir.mkdir(parents=True, exist_ok=True)

    log_path = root / "run.log"

    return JobPaths(job_id=job_id, root=root, out_dir=out_dir, seqs_dir=seqs_dir, log_path=log_path)


def write_structure(job: JobPaths, structure_bytes: bytes, filename: str) -> Path:
    """
    Writes uploaded structure bytes to:
      runs/jobs/<id>/input.pdb or input.cif
    Returns the path.
    """
    ext = _safe_ext(filename)
    input_path = job.root / f"input{ext}"
    input_path.write_bytes(structure_bytes)
    return input_path


def cleanup_job(job: JobPaths) -> None:
    """Best-effort cleanup."""
    try:
        shutil.rmtree(job.root, ignore_errors=True)
    except Exception:
        pass
