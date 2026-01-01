from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class DesignPayload(BaseModel):
    """
    JSON payload (the "JSON + file" part).
    Keep this stable so UI/API and runner stay decoupled.
    """
    chains: Optional[Union[str, List[str]]] = None
    num_sequences: int = Field(default=5, ge=1, le=200)


class DesignMetadata(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_version: str
    runtime_ms: int


class DesignedSequence(BaseModel):
    chain: str
    rank: int
    sequence: str
    diff_positions: List[int] = Field(default_factory=list)


class DesignResponse(BaseModel):
    metadata: DesignMetadata
    designed_sequences: List[DesignedSequence]
    # not required by the PDF, but useful for UI diff highlighting
    original_sequences: Dict[str, str] = Field(default_factory=dict)
