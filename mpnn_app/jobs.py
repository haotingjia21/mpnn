from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
import os
import shutil


@dataclass(frozen=True)
class JobPaths:
    job_id: str
    root: Path
    input_path: Path
    out_dir: Path


def _safe_ext(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdb"):
        return ".pdb"
    if name.endswith(".cif") or name.endswith(".mmcif"):
        return ".cif"
    # default to pdb (ProteinMPNN CLI expects pdb; CIF conversion can come later)
    return ".pdb"


def create_job_dir(base_dir: str | Path = "runs/jobs") -> JobPaths:
    """
    Creates a unique per-request job directory like:
      runs/jobs/<uuid>/
        input.pdb
        out/
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    job_id = uuid4().hex
    root = base / job_id
    root.mkdir(parents=True, exist_ok=False)

    out_dir = root / "out"
    out_dir.mkdir(parents=True, exist_ok=False)

    # placeholder input path; actual ext is derived from filename when writing
    input_path = root / "input.pdb"
    return JobPaths(job_id=job_id, root=root, input_path=input_path, out_dir=out_dir)


def write_structure(job: JobPaths, structure_bytes: bytes, filename: str) -> Path:
    """
    Writes the uploaded structure bytes to job root as input.pdb or input.cif.
    Returns the final input path.
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
