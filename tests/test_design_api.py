from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mpnn.app.api import create_app


def _repo_root() -> Path:
    # tests/ lives at <repo>/tests
    return Path(__file__).resolve().parents[1]


def _example_paths() -> tuple[Path, Path]:
    root = _repo_root()
    cif = root / "examples" / "complexes" / "cifs" / "3HTN.cif"
    pdb = root / "examples" / "complexes" / "pdbs" / "3HTN.pdb"
    assert cif.exists(), f"Missing example CIF: {cif}"
    assert pdb.exists(), f"Missing example PDB: {pdb}"
    return cif, pdb


def _write_test_config(tmp_path: Path, *, jobs_dir: Path, proteinmpnn_dir: Path) -> None:
    cfg = {
        "jobs_dir": str(jobs_dir),
        "proteinmpnn_dir": str(proteinmpnn_dir),
        "timeout_sec": 600,
        "enable_ui": False,
        "ui_defaults": {"num_seq_per_target": 5, "chains": "ALL"},
        "model_defaults": {"model_name": "v_48_020", "sampling_temp": "0.1", "batch_size": 1, "seed": 123},
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # /design requires CONTAINER_IMAGE (used for provenance)
    monkeypatch.setenv("CONTAINER_IMAGE", "test-image")

    # Ensure we run with a temp config.json in the working directory
    monkeypatch.chdir(tmp_path)

    app = create_app()
    return TestClient(app)


def test_design_payload_validation_missing_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unit test: verify pydantic validation rejects missing required fields."""

    cif, _pdb = _example_paths()

    jobs_dir = tmp_path / "runs" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    proteinmpnn_dir = Path("/opt/ProteinMPNN")
    _write_test_config(tmp_path, jobs_dir=jobs_dir, proteinmpnn_dir=proteinmpnn_dir)

    client = _client(tmp_path, monkeypatch)

    # Missing chains + num_seq_per_target
    payload = {"model_name": "v_48_020"}

    with cif.open("rb") as f:
        r = client.post(
            "/design",
            files={"structure": (cif.name, f, "application/octet-stream")},
            data={"payload": json.dumps(payload)},
        )

    assert r.status_code == 422


def test_design_integration_real_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Integration test: hit /design and run the real ProteinMPNN pipeline (no mocks)."""

    cif, _pdb = _example_paths()

    jobs_dir = tmp_path / "runs" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    # ProteinMPNN is expected to exist in the container/runtime.
    proteinmpnn_dir = Path("/opt/ProteinMPNN")
    if not proteinmpnn_dir.exists():
        pytest.skip("ProteinMPNN repo not available at /opt/ProteinMPNN in this environment")

    _write_test_config(tmp_path, jobs_dir=jobs_dir, proteinmpnn_dir=proteinmpnn_dir)

    client = _client(tmp_path, monkeypatch)

    # Use small nseq for speed; still exercises the real model end-to-end.
    payload = {
        "chains": "ALL",
        "num_seq_per_target": 1,
        "model_name": "v_48_020",
    }

    with cif.open("rb") as f:
        r = client.post(
            "/design",
            files={"structure": (cif.name, f, "application/octet-stream")},
            data={"payload": json.dumps(payload)},
        )

    assert r.status_code == 200, r.text
    data = r.json()

    assert "metadata" in data
    assert "designed_sequences" in data
    assert isinstance(data["designed_sequences"], list)
    assert len(data["designed_sequences"]) >= 1

    # Should also return originals for at least one chain
    assert "original_sequences" in data
    assert isinstance(data["original_sequences"], dict)
    assert len(data["original_sequences"]) >= 1
