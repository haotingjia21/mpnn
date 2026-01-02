from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from starlette.middleware.wsgi import WSGIMiddleware

from ..runner.design import run_design
from ..errors import ExecutionError, InputError
from ..schemas import DesignPayload

from .ui import create_dash_server

app = FastAPI(title="mpnn", version="0.1.0")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _parse_payload(payload: Optional[str]) -> DesignPayload:
    if not payload or not payload.strip():
        raise HTTPException(status_code=422, detail="Missing required form field: payload (JSON)")
    try:
        obj = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail="payload must be valid JSON") from e

    try:
        return DesignPayload.model_validate(obj)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e


@app.post("/design")
async def design(
    structure: UploadFile = File(..., description="Structure file (.pdb, .cif, .mmcif)"),
    payload: str = Form(..., description='JSON string like {"chains":["A","B"],"num_sequences":5,"model_name":"v_48_020"}'),
) -> Dict[str, Any]:
    blob = await structure.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty structure upload")

    p = _parse_payload(payload)

    base = Path(os.getenv("MPNN_JOBS_DIR", "runs/jobs"))
    job_dir = base / uuid4().hex
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    filename = (structure.filename or "input.pdb")
    uploaded_path = input_dir / Path(filename).name
    uploaded_path.write_bytes(blob)

    try:
        resp = run_design(
            job_dir=job_dir,
            structure_path=uploaded_path,
            original_filename=Path(filename).name,
            payload=p,
            # proteinmpnn_dir/timeout read from env in mpnn.design
            seed=0,
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
try:
    _dash_app, dash_server = create_dash_server()
    app.mount("/", WSGIMiddleware(dash_server))
except ModuleNotFoundError:
    # Dash is an optional dependency for tests / headless deployments.
    pass
