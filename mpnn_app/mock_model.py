from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import random
import re

# 3-letter -> 1-letter mapping (common residues)
AA3_TO_1 = {
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C",
    "GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I",
    "LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P",
    "SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V",
    # selenomethionine sometimes present
    "MSE":"M",
}

ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def parse_pdb_sequences(pdb_text: str) -> Dict[str, str]:
    """
    Very small PDB parser: builds chain sequences from ATOM records by residue index.
    Uses residue name from columns 18-20, chain ID col 22, resseq cols 23-26 (1-indexed in spec).
    """
    seen = {}  # (chain, resseq, icode) -> aa
    order = []  # preserve first-seen order per chain
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if len(line) < 26:
            continue
        resn = line[17:20].strip().upper()
        chain = (line[21] or " ").strip() or "A"
        resseq = line[22:26].strip()
        icode = line[26:27].strip() if len(line) > 26 else ""
        key = (chain, resseq, icode)
        if key in seen:
            continue
        aa = AA3_TO_1.get(resn, "X")
        seen[key] = aa
        order.append(key)

    chains: Dict[str, List[str]] = {}
    for chain, resseq, icode in order:
        chains.setdefault(chain, []).append(seen[(chain, resseq, icode)])

    return {c: "".join(seq) for c, seq in chains.items()}


def _mutate(seq: str, rng: random.Random, temperature: float) -> str:
    """
    Mutate a fraction of positions dependent on temperature.
    temperature ~1.0 => ~10% mutations, capped.
    """
    if not seq:
        # if we don't know original, generate a random 50 aa sequence
        L = 50
        return "".join(rng.choice(ALPHABET) for _ in range(L))

    frac = min(0.30, max(0.02, 0.10 * temperature))
    out = list(seq)
    for i, aa in enumerate(out):
        if aa == "X":
            # keep unknowns as random
            out[i] = rng.choice(ALPHABET)
            continue
        if rng.random() < frac:
            choices = [x for x in ALPHABET if x != aa]
            out[i] = rng.choice(choices)
    return "".join(out)


def _diff_positions(a: str, b: str) -> List[int]:
    L = min(len(a), len(b))
    diffs = [i+1 for i in range(L) if a[i] != b[i]]
    # if lengths differ, treat remaining positions as different
    if len(a) != len(b):
        diffs += list(range(L+1, max(len(a), len(b)) + 1))
    return diffs


def design_sequences_mock(
    original_sequences: Dict[str, str],
    chains: List[str],
    num_sequences: int,
    temperature: float = 1.0,
    seed: Optional[int] = None,
) -> List[Dict]:
    rng = random.Random(seed if seed is not None else 0)
    designs: List[Dict] = []
    for c in chains:
        orig = original_sequences.get(c, "")
        for k in range(num_sequences):
            # "score" here is just a deterministic-ish mock value
            seq = _mutate(orig, rng, temperature)
            score = round(-rng.random() * 5.0, 3)
            designs.append({
                "chain": c,
                "rank": k + 1,
                "sequence": seq,
                "score": score,
                "diff_positions": _diff_positions(orig, seq) if orig else [],
            })
    # sort best score (higher is "better" here) then rank
    designs.sort(key=lambda d: (d["chain"], -d["score"], d["rank"]))
    return designs
