from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_repo_git_sha(repo_dir: Path) -> str:
    """Return `git rev-parse HEAD` for a local git repo.

    For this project we use it to record the upstream ProteinMPNN code
    revision (the repo cloned into the container).
    """

    cmd = ["git", "-C", str(repo_dir), "rev-parse", "HEAD"]
    out = subprocess.check_output(cmd, text=True).strip()
    if not out:
        raise RuntimeError(f"git rev-parse returned empty output for: {repo_dir}")
    return out


def collect_versions(*, model_name: str, model_git_sha: str, container_image: str) -> Dict[str, Any]:
    """Collect lightweight version metadata.

    - `model_git_sha` is the ProteinMPNN repo commit hash (required).
    - `container_image` is the runtime image identifier (required).
    """

    if not model_git_sha:
        raise ValueError("model_git_sha is required")
    if not container_image:
        raise ValueError("container_image must be non-empty")

    try:
        app_version = importlib.metadata.version("mpnn")
    except Exception:
        app_version = ""

    return {
        "app": {"name": "mpnn", "version": app_version},
        "model": {"model_name": model_name},
        "model_git_sha": model_git_sha,
        "container_image": container_image,
    }


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_checksums(
    *,
    out_path: Path,
    job_dir: Path,
    files: Iterable[Path],
) -> List[Tuple[str, str]]:
    """Write a sha256sum-style file.

    Returns list of (hexdigest, relative_path) pairs.
    """

    rows: List[Tuple[str, str]] = []
    for p in files:
        if not p.exists() or not p.is_file():
            continue
        rel = str(p.relative_to(job_dir))
        rows.append((sha256_file(p), rel))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for h, rel in rows:
            f.write(f"{h}  {rel}\n")

    return rows
