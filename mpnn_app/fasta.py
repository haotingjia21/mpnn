from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple, Optional

from .schemas import DesignedSequence


def parse_fasta_text(text: str) -> List[Tuple[str, str]]:
    """
    Minimal FASTA parser:
      returns list of (header_without_>, sequence_string)
    Handles multi-line sequences.
    """
    records: List[Tuple[str, str]] = []
    header: Optional[str] = None
    seq_chunks: List[str] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            # flush previous
            if header is not None:
                records.append((header, "".join(seq_chunks)))
            header = line[1:].strip()
            seq_chunks = []
        else:
            # sequence line (remove spaces)
            seq_chunks.append(line.replace(" ", ""))

    if header is not None:
        records.append((header, "".join(seq_chunks)))

    return records


def read_fasta_file(path: Path) -> List[Tuple[str, str]]:
    return parse_fasta_text(path.read_text(encoding="utf-8", errors="ignore"))


def find_fasta_files(out_dir: Path) -> List[Path]:
    """
    ProteinMPNN typically writes:
      <out_dir>/seqs/*.fa
    We support .fa/.fasta and return sorted list for deterministic ordering.
    """
    seqs_dir = out_dir / "seqs"
    if not seqs_dir.exists():
        return []
    files = list(seqs_dir.glob("*.fa")) + list(seqs_dir.glob("*.fasta"))
    return sorted(set(files))


def _split_multichain_sequence(seq: str, chains: List[str]) -> List[str]:
    """
    Heuristic splitter for multi-chain outputs.
    If ProteinMPNN outputs multi-chain sequences in a single record separated by '/',
    we split and align with chains order.

    If we can't confidently split, return [seq] as a single chunk.
    """
    if len(chains) <= 1:
        return [seq]

    # common separators seen in some pipelines
    for sep in ["/", ":", "|", ","]:
        if sep in seq:
            parts = [p.strip() for p in seq.split(sep) if p.strip()]
            if len(parts) == len(chains):
                return parts

    return [seq]


def load_designed_sequences_from_out(out_dir: Path, chains: List[str]) -> List[DesignedSequence]:
    """
    Reads ProteinMPNN outputs from <out_dir>/seqs/*.fa and converts to DesignedSequence.

    Ranking:
      - rank is assigned by record order within each fasta file (1..N)

    Chain mapping:
      - if one chain requested -> all records map to that chain
      - if multiple chains requested and a record sequence can be split into the same number
        of chains, we emit one DesignedSequence per chain with the SAME rank.
      - otherwise, we emit a single DesignedSequence with chain="A,B" (joined) so the API
        still returns something predictable.
    """
    fasta_files = find_fasta_files(out_dir)
    designed: List[DesignedSequence] = []

    chain_list = [c for c in chains if c]  # sanitize

    for fp in fasta_files:
        records = read_fasta_file(fp)
        for i, (_hdr, seq) in enumerate(records):
            rank = i + 1

            if len(chain_list) <= 1:
                chain = chain_list[0] if chain_list else "A"
                designed.append(
                    DesignedSequence(chain=chain, rank=rank, sequence=seq, diff_positions=[])
                )
                continue

            parts = _split_multichain_sequence(seq, chain_list)
            if len(parts) == len(chain_list):
                for c, part in zip(chain_list, parts):
                    designed.append(
                        DesignedSequence(chain=c, rank=rank, sequence=part, diff_positions=[])
                    )
            else:
                designed.append(
                    DesignedSequence(chain=",".join(chain_list), rank=rank, sequence=seq, diff_positions=[])
                )

    return designed
