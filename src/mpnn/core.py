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
        """Default ProteinMPNN arguments for this deployment.

        These are merged with per-request overrides.
        """

        model_config = ConfigDict(extra="forbid", protected_namespaces=())

        model_name: str
        num_seq_per_target: int = Field(ge=1)
        sampling_temp: str
        batch_size: int = Field(ge=1)

    jobs_dir: Path
    proteinmpnn_dir: Path
    timeout_sec: int = Field(ge=1)
    mock: bool
    enable_ui: bool
    model_defaults: ModelDefaults


def load_config(path: Path) -> AppConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


def find_default_config_path() -> Path:
    return Path("config.json")


# ---------------------------
# API schemas
# ---------------------------


class _BaseModel(BaseModel):
    """Project-wide BaseModel.

    Pydantic reserves the `model_` namespace for internal attributes. Our
    schema fields (e.g. `model_name`, `model_version`) are part of the
    contract, so we explicitly allow them.
    """

    model_config = {"protected_namespaces": ()}


class DesignPayload(_BaseModel):
    # chains can be "A" or ["A","B"]; omit/empty => "all chains"
    chains: Optional[Union[str, List[str]]] = None

    # ProteinMPNN args (optional overrides; defaults come from config.json)
    num_seq_per_target: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("num_seq_per_target", "num_sequences", "Num_sequences"),
        serialization_alias="num_seq_per_target",
    )
    sampling_temp: Optional[str] = Field(default=None, serialization_alias="sampling_temp")
    batch_size: Optional[int] = Field(default=None, serialization_alias="batch_size")
    model_name: Optional[str] = Field(default=None, serialization_alias="model_name")


class DesignMetadata(_BaseModel):
    model_version: str
    runtime_ms: int
    seed: int = 0


class DesignedSequence(_BaseModel):
    chain: str
    rank: int
    sequence: str


class DesignResponse(_BaseModel):
    metadata: DesignMetadata
    designed_sequences: List[DesignedSequence]
    original_sequences: Dict[str, str] = Field(default_factory=dict)
