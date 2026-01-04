from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from starlette.middleware.wsgi import WSGIMiddleware

from ..core import AppConfig, ExecutionError, InputError, DesignPayload, load_config
from ..runner.design import run_design


def _parse_payload(payload: str) -> DesignPayload:
    if not payload.strip():
        raise HTTPException(status_code=422, detail="Missing required form field: payload (JSON)")
    try:
        obj = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail="payload must be valid JSON") from e

    # Allow empty/missing fields and apply server-side defaults later.
    if isinstance(obj, dict):
        # chains: empty/missing -> all chains
        if obj.get("chains") is None:
            obj["chains"] = ""
        if isinstance(obj.get("chains"), str) and obj.get("chains").strip().upper() == "ALL":
            raise HTTPException(status_code=422, detail="chains='ALL' is not supported; use empty string for all chains")

        # num_seq_per_target: empty string -> treat as missing
        if obj.get("num_seq_per_target") == "" or obj.get("num_sequences") == "" or obj.get("Num_sequences") == "":
            # remove any empty aliases so pydantic doesn't try to parse them
            for k in ("num_seq_per_target", "num_sequences", "Num_sequences"):
                if obj.get(k) == "":
                    obj.pop(k, None)


    try:
        return DesignPayload.model_validate(obj)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e


def create_app() -> FastAPI:
    """Create a FastAPI app.

    Runtime configuration is loaded from a JSON file (fail-fast).

    run_metadata.json records `model_git_sha` (ProteinMPNN repo revision) plus app_version.
    """

    # Config path is intentionally non-optional: we always load ./config.json.
    cfg = load_config(Path("config.json"))
    app = FastAPI(title="mpnn", version="0.1.0")
    app.state.config = cfg

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/design")
    async def design(
        structure: UploadFile = File(..., description="Structure file (.pdb, .cif, .mmcif)"),
        payload: str = Form(
            ...,
            description=(
                'JSON string. Fields: "chains" (empty/missing for all-chains) and '
                '"num_seq_per_target" (empty/missing uses server default). Optional field: "model_name".'
            ),
        ),
    ) -> Dict[str, Any]:
        blob = await structure.read()
        if not blob:
            raise HTTPException(status_code=400, detail="Empty structure upload")

        p = _parse_payload(payload)
        cfg: AppConfig = app.state.config

        # Apply server-side defaults for empty/missing fields.
        if p.num_seq_per_target is None:
            p = p.model_copy(update={"num_seq_per_target": cfg.model_defaults.num_seq_per_target})
        if p.chains is None:
            p = p.model_copy(update={"chains": ""})

        job_dir = Path(cfg.jobs_dir) / uuid4().hex
        inputs_dir = job_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        filename = (structure.filename or "input.pdb")
        uploaded_path = inputs_dir / Path(filename).name
        uploaded_path.write_bytes(blob)

        try:
            resp = run_design(
                job_dir=job_dir,
                structure_path=uploaded_path,
                original_filename=Path(filename).name,
                payload=p,
                model_defaults=cfg.model_defaults,
                proteinmpnn_dir=cfg.proteinmpnn_dir,
                timeout_sec=cfg.timeout_sec,
            )
        except InputError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except ExecutionError as e:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": str(e),
                    "returncode": e.returncode,
                    "stdout": e.stdout,
                    "stderr": e.stderr,
                },
            ) from e

        return resp.model_dump()

    # Mount Dash at "/" LAST so /health and /design match first
    if cfg.enable_ui:
        from .ui import create_dash_server

        _dash_app, dash_server = create_dash_server(model_defaults=cfg.model_defaults)
        app.mount("/", WSGIMiddleware(dash_server))

    return app


# Run with:
#   uvicorn mpnn.app.api:create_app --factory --host 0.0.0.0 --port 8000
