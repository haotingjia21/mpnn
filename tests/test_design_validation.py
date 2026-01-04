from __future__ import annotations

import json


def _post(client, payload: dict | str):
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    return client.post(
        "/design",
        files={"structure": ("toy.pdb", b"X", "chemical/x-pdb")},
        data={"payload": payload},
    )


def test_design_missing_required_multipart_fields(client):
    assert client.post("/design").status_code == 422


def test_design_rejects_bad_payload_json(client):
    r = _post(client, "{not-json")
    assert r.status_code == 422
    assert r.json()["detail"] == "payload must be valid JSON"


def test_design_rejects_num_sequences_invalid(client):
    # schema: num_sequences >= 1 and <= 10
    assert _post(client, {"num_sequences": 11}).status_code == 422
    assert _post(client, {"num_sequences": -1}).status_code == 422


def test_design_rejects_chains_invalid(client):
    # schema: chains must be str or list[str]
    assert _post(client, {"chains": 123}).status_code == 422


