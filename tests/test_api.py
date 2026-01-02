import json
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mpnn.app.api import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTAINER_IMAGE", "mpnn:test")
    cfg = {
        "jobs_dir": str(tmp_path / "jobs"),
        "proteinmpnn_dir": "/opt/ProteinMPNN",
        "timeout_sec": 600,
        "mock": True,
        "enable_ui": False,
        "model_defaults": {
            "model_name": "v_48_020",
            "num_seq_per_target": 5,
            "sampling_temp": "0.1",
            "batch_size": 1,
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    app = create_app(cfg_path)
    return TestClient(app)


def test_missing_payload_422(client):
    r = client.post("/design", files={"structure": ("toy.pdb", b"ATOM", "application/octet-stream")})
    assert r.status_code == 422


def test_design_writes_manifest_and_metadata(client, tmp_path):
    payload = {"chains": "A", "num_sequences": 3, "model_name": "v_48_030"}
    body = b"ATOM\n"  # mock mode does not parse, extension still matters

    r = client.post(
        "/design",
        files={"structure": ("toy.pdb", body, "application/octet-stream")},
        data={"payload": json.dumps(payload)},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["metadata"]["model_version"] == "v_48_030"
    assert {d["chain"] for d in data["designed_sequences"]} == {"A"}

    # Ensure job artifact folder exists under MPNN_JOBS_DIR
    jobs_dir = tmp_path / "jobs"
    job_dirs = [p for p in jobs_dir.iterdir() if p.is_dir()]
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]

    # Folder contract
    assert (job_dir / "inputs" / "toy.pdb").exists()
    assert (job_dir / "inputs" / "manifest.json").exists()
    assert (job_dir / "artifacts" / "toy.pdb").exists()
    assert (job_dir / "artifacts" / "parsed_pdbs.jsonl").exists()
    assert (job_dir / "artifacts" / "chain_ids.jsonl").exists()
    assert (job_dir / "logs" / "run.log").exists()
    assert (job_dir / "model_outputs" / "seqs" / "toy_res.fa").exists()
    assert (job_dir / "responses" / "response.json").exists()
    assert (job_dir / "metadata" / "checksums.sha256").exists()
    assert (job_dir / "metadata" / "versions.json").exists()
    assert (job_dir / "formatted_outputs").is_dir()

    # Manifest contains checksums + versions
    manifest = json.loads((job_dir / "inputs" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["original_filename"] == "toy.pdb"
    assert manifest["effective"]["model_name"] == "v_48_030"
    assert manifest["effective"]["num_seq_per_target"] == 3
    assert "checksums" in manifest and "input_sha256" in manifest["checksums"]
    assert "versions" in manifest and "model_name" in manifest["versions"]
    assert manifest["versions"]["model_git_sha"] == "0" * 40
    assert manifest["versions"]["container_image"]

    # checksums.sha256 includes the raw input checksum and relative path
    expected_input_sha = hashlib.sha256(body).hexdigest()
    sums = (job_dir / "metadata" / "checksums.sha256").read_text(encoding="utf-8")
    assert f"{expected_input_sha}  inputs/toy.pdb" in sums


def test_chains_omitted_defaults_to_all(client):
    payload = {}  # omit chains and model params -> use config model_defaults
    r = client.post(
        "/design",
        files={"structure": ("complex.pdb", b"ATOM\n", "application/octet-stream")},
        data={"payload": json.dumps(payload)},
    )
    assert r.status_code == 200
    data = r.json()
    assert {d["chain"] for d in data["designed_sequences"]} == {"A", "B"}
    # Default num_seq_per_target=5 -> 5 ranks x 2 chains
    assert len(data["designed_sequences"]) == 10
