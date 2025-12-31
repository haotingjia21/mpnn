from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple, Union

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .mock_model import design_sequences_mock, parse_pdb_sequences


app = FastAPI(title="ProteinMPNN Mini-Service (Mock)", version="0.1.0")

app.mount("/static", StaticFiles(directory="mpnn_app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # Serve minimal single-page UI
    with open("mpnn_app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _parse_chains(chains_raw: Optional[str]) -> List[str]:
    """
    Accept:
      - None/"" -> []
      - "A" or "A,B" or "A B"
      - JSON list string like '["A","B"]'
    """
    if not chains_raw:
        return []
    s = chains_raw.strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            arr = __import__("json").loads(s)
            if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
                raise ValueError
            return [x.strip() for x in arr if x.strip()]
        except Exception as e:
            raise HTTPException(status_code=422, detail="chains must be like A or A,B or a JSON list") from e
    # split on commas or whitespace
    parts = [p.strip() for p in __import__("re").split(r"[,\s]+", s) if p.strip()]
    return parts


@app.post("/design")
async def design(
    structure: UploadFile = File(..., description="PDB or CIF structure file"),
    chains: Optional[str] = Form(None, description='Chain(s) to design: "A" or "A,B" or ["A","B"]'),
    num_sequences: int = Form(5, ge=1, le=200),
    seed: Optional[int] = Form(None),
    temperature: float = Form(1.0, ge=0.01, le=5.0),
) -> Dict:
    t0 = time.perf_counter()

    filename = (structure.filename or "").lower()
    data = await structure.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty structure upload")

    ext = ".pdb" if filename.endswith(".pdb") else ".cif" if filename.endswith(".cif") else None
    if ext is None:
        # allow unknown names but attempt PDB parse by content
        ext = ".pdb"

    chain_list = _parse_chains(chains)

    original_sequences: Dict[str, str] = {}
    if ext == ".pdb":
        try:
            original_sequences = parse_pdb_sequences(data.decode("utf-8", errors="ignore"))
        except Exception as e:
            raise HTTPException(status_code=400, detail="Failed to parse PDB") from e
    else:
        # Minimal mock: accept CIF but cannot reliably extract sequence here
        original_sequences = {}

    if chain_list:
        # ensure requested chains exist if we were able to parse originals
        if original_sequences:
            missing = [c for c in chain_list if c not in original_sequences]
            if missing:
                raise HTTPException(status_code=422, detail=f"Chain(s) not found in structure: {missing}")
    else:
        # default: all chains found (if parse succeeded), else empty
        chain_list = sorted(original_sequences.keys()) if original_sequences else []

    # If still empty, we can't infer; allow one "A" with empty original
    if not chain_list:
        chain_list = ["A"]

    designs = design_sequences_mock(
        original_sequences=original_sequences,
        chains=chain_list,
        num_sequences=num_sequences,
        temperature=temperature,
        seed=seed,
    )

    runtime_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "metadata": {
            "model_version": "mock-0.1.0",
            "runtime_ms": runtime_ms,
            "chains": chain_list,
            "num_sequences": num_sequences,
            "temperature": temperature,
            "seed": seed,
        },
        "original_sequences": original_sequences,  # may be empty for CIF
        "designed_sequences": designs,
    }
