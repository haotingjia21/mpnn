from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Allow running pytest without installing the package.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def cfg_dict(tmp_path: Path) -> dict:
    return {
        "jobs_dir": str(tmp_path / "runs"),
        "proteinmpnn_dir": str(tmp_path / "ProteinMPNN"),
        "timeout_sec": 30,
        "max_concurrent_jobs": 2,
        "model_defaults": {
            "model_name": "mock",
            "sampling_temp": "0.1",
            "batch_size": 1,
            "seed": 0,
            "num_sequences": 2,
        },
    }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cfg_dict: dict) -> TestClient:
    (tmp_path / "config.json").write_text(json.dumps(cfg_dict), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONTAINER_IMAGE", "test-image")

    from mpnn.app.api import create_app

    return TestClient(create_app())
