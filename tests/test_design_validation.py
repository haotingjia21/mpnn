from __future__ import annotations

import json
from mpnn.core import DesignMetadata, DesignedSequence, DesignResponse
import mpnn.app.api as api


def _post(client, payload: dict | str):
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    return client.post(
        "/design",
        files={"structure": ("toy.pdb", b"X", "chemical/x-pdb")},
        data={"payload": payload},
    )


def test_missing_required_multipart_fields(client):
    assert client.post("/design").status_code == 422


def test_bad_payload_json(client):
    r = _post(client, "{not-json")
    assert r.status_code == 422
    assert r.json()["detail"] == "payload must be valid JSON"


def test_num_sequences_invalid(client):
    # schema: num_sequences >= 1 and <= 10
    assert _post(client, {"num_sequences": 11}).status_code == 422
    assert _post(client, {"num_sequences": -1}).status_code == 422


def test_chains_invalid(client):
    # schema: chains must be str or list[str]
    assert _post(client, {"chains": 123}).status_code == 422


def test_valid_request(client, monkeypatch):
    def fake_run_design(*args, **kwargs):
        return DesignResponse(
            metadata=DesignMetadata(model_version="mock", runtime_ms=1),
            designed_sequences=[DesignedSequence(chain="A", rank=1, sequence="ACDE")],
            original_sequences={"A": "AAAA"},
        )
    monkeypatch.setattr(api, "run_design", fake_run_design)

    r = _post(client, {"chains": None, "num_sequences": 1})
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"metadata", "designed_sequences", "original_sequences"}
