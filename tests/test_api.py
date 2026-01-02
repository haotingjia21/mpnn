import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import mpnn.app.api as api
from mpnn import DesignMetadata, DesignResponse, DesignedSequence


def _fake_run_design():
    def fake(
        *,
        job_dir: Path,
        structure_path: Path,
        original_filename: str,
        payload,
        proteinmpnn_dir=None,
        timeout_sec=None,
        seed: int = 0,
    ):
        # Emulate core artifact layout
        (job_dir / "output" / "seqs").mkdir(parents=True, exist_ok=True)
        (job_dir / "output").mkdir(parents=True, exist_ok=True)
        (job_dir / "output" / "run.log").write_text("fake log", encoding="utf-8")

        # emulate response
        chains = payload.chains
        # normalize like server would: accept "A" or ["A","B"]
        if chains is None or (isinstance(chains, str) and not chains.strip()) or (isinstance(chains, list) and len(chains) == 0):
            designed = [
                DesignedSequence(chain="A", rank=1, sequence="AAAA"),
                DesignedSequence(chain="B", rank=1, sequence="BBBB"),
            ]
        else:
            designed = [DesignedSequence(chain="A", rank=1, sequence="AAAA")]

        resp = DesignResponse(
            metadata=DesignMetadata(model_version=payload.model_name, runtime_ms=123, seed=seed),
            designed_sequences=designed,
            original_sequences={"A": "AAAA", "B": "CCCC"},
        )

        # core writes response.json
        (job_dir / "output" / "response.json").write_text(
            json.dumps(resp.model_dump(), indent=2),
            encoding="utf-8",
        )
        # also mimic FASTA artifact naming
        stem = Path(original_filename).stem or "input"
        (job_dir / "output" / "seqs" / f"{stem}_res.fa").write_text(">x\nAAAA\n", encoding="utf-8")

        return resp

    return fake


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MPNN_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(api, "run_design", _fake_run_design())
    return TestClient(api.app)


def test_missing_payload_422(client):
    r = client.post("/design", files={"structure": ("toy.pdb", b"ATOM", "application/octet-stream")})
    assert r.status_code == 422


def test_design_ok_and_writes_artifacts(client, tmp_path):
    payload = {"chains": "A", "num_sequences": 5, "model_name": "v_48_030"}
    r = client.post(
        "/design",
        files={"structure": ("toy.pdb", b"ATOM", "application/octet-stream")},
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
    assert (job_dir / "input" / "toy.pdb").exists()
    assert (job_dir / "output" / "response.json").exists()
    assert (job_dir / "output" / "run.log").exists()
    assert (job_dir / "output" / "seqs" / "toy_res.fa").exists()


def test_chains_omitted_defaults_to_all(client):
    payload = {"num_sequences": 5, "model_name": "v_48_020"}  # omit chains
    r = client.post(
        "/design",
        files={"structure": ("complex.pdb", b"ATOM", "application/octet-stream")},
        data={"payload": json.dumps(payload)},
    )
    assert r.status_code == 200
    data = r.json()
    assert {d["chain"] for d in data["designed_sequences"]} == {"A", "B"}
