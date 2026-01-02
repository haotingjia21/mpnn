from __future__ import annotations

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, AliasChoices


class _BaseModel(BaseModel):
    """Project-wide BaseModel.

    Pydantic reserves the `model_` namespace for internal attributes. Our schema
    fields (e.g. `model_name`, `model_version`) are part of the HW contract, so
    we explicitly allow them.
    """

    model_config = {"protected_namespaces": ()}


class DesignPayload(_BaseModel):
    # HW: chains can be "A" or ["A","B"]; omit/empty => "all chains"
    chains: Optional[Union[str, List[str]]] = None

    # HW: Num_sequences default 5 (accept both num_sequences and Num_sequences)
    num_sequences: int = Field(
        default=5,
        validation_alias=AliasChoices("num_sequences", "Num_sequences"),
        serialization_alias="num_sequences",
    )

    # ProteinMPNN model choice (UI dropdown / API payload)
    model_name: str = Field(default="v_48_020")


class DesignMetadata(_BaseModel):
    model_version: str
    runtime_ms: int
    seed: int = 0  # we always pass --seed 0


class DesignedSequence(_BaseModel):
    chain: str
    rank: int
    sequence: str


class DesignResponse(_BaseModel):
    metadata: DesignMetadata
    designed_sequences: List[DesignedSequence]
    original_sequences: Dict[str, str] = Field(default_factory=dict)
