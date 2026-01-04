from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, AliasChoices
from pydantic.config import ConfigDict


# ---------------------------
# Errors (fail-fast)
# ---------------------------


class CoreError(Exception):
    """Base error type for mpnn."""


class InputError(CoreError):
    """Raised when user input is invalid."""


class ExecutionError(CoreError):
    """Raised when an external command fails."""

    def __init__(self, message: str, *, returncode: int, stdout: str, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
# ---------------------------
# Service config (JSON file)
# ---------------------------


class AppConfig(BaseModel):
    """Service configuration loaded from a JSON file."""

    # Allow `model_defaults` without pydantic's protected `model_` namespace warnings.
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    class ModelDefaults(BaseModel):
        """Default ProteinMPNN arguments for this deployment."""

        model_config = ConfigDict(extra="forbid", protected_namespaces=())

        # Defaults that are safe to apply server-side when a request omits them.
        model_name: str
        sampling_temp: str
        batch_size: int = Field(ge=1)
        seed: int = Field(ge=0)
        num_sequences: int = Field(ge=1)

    jobs_dir: Path
    proteinmpnn_dir: Path
    timeout_sec: int = Field(ge=1)
    enable_ui: bool
    model_defaults: ModelDefaults


def load_config(path: Path) -> AppConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


# ---------------------------
# API schemas
# ---------------------------


class _BaseModel(BaseModel):
    """Project-wide BaseModel."""

    model_config = {"protected_namespaces": ()}


class DesignPayload(_BaseModel):
    # chains:
    #   - empty / missing -> all chains
    #   - "A" or "A,B"
    #

    chains: Optional[Union[str, List[str]]] = Field(default="")

    # ProteinMPNN args
    # If missing/empty, the API will apply cfg.model_defaults.num_sequences.
    num_sequences: Optional[int] = Field(default=None, ge=1, le=10)
    model_name: Optional[str] = Field(default=None, serialization_alias="model_name")


class DesignMetadata(_BaseModel):
    model_version: str
    runtime_ms: int


class DesignedSequence(_BaseModel):
    chain: str
    rank: int
    sequence: str


class DesignResponse(_BaseModel):
    metadata: DesignMetadata
    designed_sequences: List[DesignedSequence]
    original_sequences: Dict[str, str] = Field(default_factory=dict)