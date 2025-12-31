from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError


app = FastAPI(title="mpnn-mock", version="0.1.0")

app.mount("/static", StaticFiles(directory="mpnn_app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    with open("mpnn_app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health() -> Dict[str, str]:
    # Spec: returns {status:"ok"}
    return {"status": "ok"}


# ---------------------------
# Payload schema (JSON part)
# ---------------------------

class DesignPayload(BaseModel):
    chains: Optional[Union[str, List[str]]] = None
    num_sequences: int = Field(default=5, ge=1, le=200)


def _normalize_chains(chains: Optional[Union[str, List[str]]]) -> List[str]:
    if chains is None:
        return []
    if isinstance(chains, list):
        out = [c.strip() for c in chains if isinstance(c, str) and c.strip()]
        return out
    if isinstance(chains, str):
        s = chains.strip()
        if not s:
            return []
        return [p for p in re.split(r"[,\s]+", s) if p]
    return []


# ---------------------------
# Mock model + tiny PDB parser
# ---------------------------

AA3_TO_1 = {
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C",
    "GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I",
    "LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P",
    "SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V",
    "MSE":"M",
}
ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def parse_pdb_sequences(pdb_text: str) -> Dict[str, str]:
    """Tiny PDB ATOM parser -> chain sequences (1-letter)."""
    seen: Dict[tuple, str] = {}
    order: List[tuple] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or len(line) < 27:
            continue
        resn = line[17:20].strip().upper()
        chain = (line[21].strip() or "A")
        resseq = line[22:26].strip()
        icode = line[26:27].strip()
        key = (chain, resseq, icode)
        if key in seen:
            continue
        seen[key] = AA3_TO_1.get(resn, "X")
        order.append(key)

    out: Dict[str, List[str]] = {}
    for chain, resseq, icode in order:
        out.setdefault(chain, []).append(seen[(chain, resseq, icode)])
    return {c: "".join(v) for c, v in out.items()}


def _mutate(seq: str, rng: random.Random, frac: float = 0.10) -> str:
    if not seq:
        return "".join(rng.choice(ALPHABET) for _ in range(50))
    out = list(seq)
    for i, aa in enumerate(out):
        if aa == "X":
            out[i] = rng.choice(ALPHABET)
        elif rng.random() < frac:
            out[i] = rng.choice([x for x in ALPHABET if x != aa])
    return "".join(out)


def _diff_positions(a: str, b: str) -> List[int]:
    L = min(len(a), len(b))
    diffs = [i + 1 for i in range(L) if a[i] != b[i]]
    if len(a) != len(b):
        diffs += list(range(L + 1, max(len(a), len(b)) + 1))
    return diffs


def _design_mock(original: Dict[str, str], chains: List[str], num_sequences: int) -> List[Dict[str, Any]]:
    rng = random.Random(0)
    designs: List[Dict[str, Any]] = []
    for c in chains:
        orig = original.get(c, "")
        for k in range(num_sequences):
            seq = _mutate(orig, rng)
            designs.append(
                {
                    "chain": c,
                    "rank": k + 1,
                    "sequence": seq,
                    "diff_positions": _diff_positions(orig, seq) if orig else [],
                }
            )
    return designs


def _parse_payload_json(payload: Optional[str], chains_fallback: Optional[str], nseq_fallback: int) -> DesignPayload:
    """
    Spec says "JSON + file". We accept JSON via multipart form field `payload`.
    For convenience, also accept fallback form fields `chains` and `num_sequences`.
    """
    if payload is None or not payload.strip():
        # fallback
        return DesignPayload(chains=chains_fallback, num_sequences=nseq_fallback)

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
    structure: UploadFile = File(..., description="Protein structure file (PDB/CIF)"),
    payload: Optional[str] = Form(None, description='JSON string with {"chains": "A" or ["A","B"], "num_sequences": 5}'),
    # fallbacks (optional, to be nice)
    chains: Optional[str] = Form(None),
    num_sequences: int = Form(5, ge=1, le=200),
) -> Dict[str, Any]:
    t0 = time.perf_counter()

    blob = await structure.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty structure upload")

    p = _parse_payload_json(payload, chains, num_sequences)
    chain_list = _normalize_chains(p.chains)

    name = (structure.filename or "").lower()
    is_pdb = name.endswith(".pdb") or (not name.endswith(".cif"))

    original: Dict[str, str] = {}
    if is_pdb:
        original = parse_pdb_sequences(blob.decode("utf-8", errors="ignore"))

    if not chain_list:
        chain_list = sorted(original.keys()) if original else ["A"]

    designs = _design_mock(original, chain_list, p.num_sequences)
    runtime_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "metadata": {"model_version": "mock-0.1.0", "runtime_ms": runtime_ms},
        "designed_sequences": designs,
        # include originals for UI diff highlight (not forbidden by spec)
        "original_sequences": original,
    }
