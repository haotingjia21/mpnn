from __future__ import annotations
from typing import Dict, List, Optional
import random
import time
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="mpnn-mock", version="0.0.1")

# UI
app.mount("/static", StaticFiles(directory="mpnn_app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    with open("mpnn_app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


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
    seen = {}  # (chain, resseq, icode) -> aa
    order = []
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


def _parse_chains(chains: Optional[str]) -> List[str]:
    if not chains:
        return []
    s = chains.strip()
    if not s:
        return []
    return [p for p in re.split(r"[,\s]+", s) if p]


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


@app.post("/design")
async def design(
    structure: UploadFile = File(...),
    chains: Optional[str] = Form(None),
    num_sequences: int = Form(5, ge=1, le=200),
) -> Dict:
    t0 = time.perf_counter()
    data = await structure.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty structure upload")

    name = (structure.filename or "").lower()
    is_pdb = name.endswith(".pdb") or (not name.endswith(".cif"))

    original: Dict[str, str] = {}
    if is_pdb:
        original = parse_pdb_sequences(data.decode("utf-8", errors="ignore"))

    chain_list = _parse_chains(chains) or (sorted(original.keys()) if original else ["A"])

    rng = random.Random(0)
    designs = []
    for c in chain_list:
        orig = original.get(c, "")
        for k in range(num_sequences):
            seq = _mutate(orig, rng)
            designs.append({
                "chain": c,
                "rank": k + 1,
                "sequence": seq,
                "diff_positions": _diff_positions(orig, seq) if orig else [],
            })

    return {
        "metadata": {"runtime_ms": int((time.perf_counter() - t0) * 1000)},
        "original_sequences": original,
        "designed_sequences": designs,
    }
