from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from Bio import SeqIO

from .schemas import DesignedSequence


def find_fasta_files(out_dir: Path) -> List[Path]:
    seqs_dir = out_dir / "seqs"
    if not seqs_dir.exists():
        return []
    files = list(seqs_dir.glob("*.fa")) + list(seqs_dir.glob("*.fasta"))
    return sorted(set(files))


def _split_multichain_sequence(seq: str, chains: List[str]) -> List[str]:
    """Best-effort splitter when one record encodes multiple chains."""
    if len(chains) <= 1:
        return [seq]
    for sep in ["/", ":", "|", ","]:
        if sep in seq:
            parts = [p.strip() for p in seq.split(sep) if p.strip()]
            if len(parts) == len(chains):
                return parts
    return [seq]


def load_original_and_designed_from_out(out_dir: Path, chains: List[str]) -> Tuple[Dict[str, str], List[DesignedSequence]]:
    """
    ProteinMPNN FASTA convention (per your observation):
      - record[0] = original sequence
      - record[1:] = designed sequences

    Returns:
      (original_sequences_by_chain, designed_sequences)

    Chain mapping:
      - if chains has 1 entry -> map to that chain
      - if chains has N>1 and sequence can be split into N parts -> map each part to each chain
      - else -> map to ",".join(chains) as a single combined chain key
    """
    fasta_files = find_fasta_files(out_dir)
    if not fasta_files:
        return {}, []

    chain_list = [c for c in chains if c] or ["A"]  # minimal fallback

    original_by_chain: Dict[str, str] = {}
    designed: List[DesignedSequence] = []

    # In practice ProteinMPNN usually emits one fasta per target; handle multiple anyway.
    global_rank = 1
    for fp in fasta_files:
        records = list(SeqIO.parse(str(fp), "fasta"))
        if not records:
            continue

        # First record is ORIGINAL
        orig_seq = str(records[0].seq)

        if len(chain_list) <= 1:
            original_by_chain.setdefault(chain_list[0], orig_seq)
        else:
            parts = _split_multichain_sequence(orig_seq, chain_list)
            if len(parts) == len(chain_list):
                for c, part in zip(chain_list, parts):
                    original_by_chain.setdefault(c, part)
            else:
                original_by_chain.setdefault(",".join(chain_list), orig_seq)

        # Remaining records are DESIGNS
        for rec in records[1:]:
            seq = str(rec.seq)
            if len(chain_list) <= 1:
                designed.append(DesignedSequence(chain=chain_list[0], rank=global_rank, sequence=seq, diff_positions=[]))
                global_rank += 1
                continue

            parts = _split_multichain_sequence(seq, chain_list)
            if len(parts) == len(chain_list):
                # same rank for all chains of this "design"
                for c, part in zip(chain_list, parts):
                    designed.append(DesignedSequence(chain=c, rank=global_rank, sequence=part, diff_positions=[]))
                global_rank += 1
            else:
                designed.append(
                    DesignedSequence(chain=",".join(chain_list), rank=global_rank, sequence=seq, diff_positions=[])
                )
                global_rank += 1

    return original_by_chain, designed
