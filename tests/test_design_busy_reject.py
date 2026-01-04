from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi.testclient import TestClient

import mpnn.app.api as api
from mpnn.core import DesignMetadata, DesignedSequence, DesignResponse


def _post(client: TestClient, payload: dict | str):
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    return client.post(
        "/design",
        files={"structure": ("toy.pdb", b"X", "chemical/x-pdb")},
        data={"payload": payload},
    )


def test_reject_when_busy_returns_503(tmp_path: Path, monkeypatch, cfg_dict: dict):
    # Limit concurrency to 1 via config.json default (env var can still override).
    cfg_dict["max_concurrent_jobs"] = 1

    # Arrange: write config.json in cwd (create_app loads it from Path("config.json"))
    (tmp_path / "config.json").write_text(json.dumps(cfg_dict), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    started = threading.Event()
    release = threading.Event()

    def fake_run_design(*args, **kwargs):
        # The limiter has been acquired before run_design is called.
        started.set()
        release.wait(timeout=5)
        return DesignResponse(
            metadata=DesignMetadata(model_version="mock", runtime_ms=1),
            designed_sequences=[DesignedSequence(chain="A", rank=1, sequence="ACDE")],
            original_sequences={"A": "AAAA"},
        )

    monkeypatch.setattr(api, "run_design", fake_run_design)

    app = api.create_app()

    with TestClient(app) as client:
        r1_holder = {}

        def _call_1():
            r1_holder["r1"] = _post(client, {"chains": "A", "num_sequences": 1})

        t = threading.Thread(target=_call_1, daemon=True)
        t.start()

        assert started.wait(timeout=2), "first request never entered run_design"

        # Act: second request should be rejected immediately (no waiting)
        r2 = _post(client, {"chains": "A", "num_sequences": 1})

        # Assert: rejected with retry hint
        assert r2.status_code == 503
        assert r2.headers.get("Retry-After") == "1"

        # Let first request complete
        release.set()
        t.join(timeout=5)

        r1 = r1_holder["r1"]
        assert r1.status_code == 200
