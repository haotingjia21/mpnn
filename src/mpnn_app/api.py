from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from starlette.middleware.wsgi import WSGIMiddleware

from .dash_ui import create_dash_server
from .runner import RunnerError, RunnerInputError, ProteinMPNNExecutionError, get_runner
from .schemas import DesignPayload

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
    payload: str = Form(..., description='JSON string like {"chains":["A","B"],"num_sequences":5}'),
) -> Dict[str, Any]:
    blob = await structure.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty structure upload")

    p = _parse_payload(payload)
    runner = get_runner()

    try:
        result = runner.design(structure_bytes=blob, filename=structure.filename or "", payload=p)
    except RunnerInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ProteinMPNNExecutionError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "returncode": e.returncode,
                "stdout": e.stdout,
                "stderr": e.stderr,
            },
        ) from e
    except RunnerError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return result.model_dump()


# Mount Dash at "/" LAST so /health and /design match first
_dash_app, dash_server = create_dash_server()
app.mount("/", WSGIMiddleware(dash_server))
