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

        # Defaults that are safe to apply server-side when a request omits them.
        # NOTE: num_seq_per_target and chains are request-required (see DesignPayload).
        model_name: str
        sampling_temp: str
        batch_size: int = Field(ge=1)
        seed: int = Field(ge=0)

    class UiDefaults(BaseModel):
        """Defaults used only by the UI (client-side convenience).

        These are NOT applied implicitly by the /design endpoint. The UI will
        always send explicit values so the server can treat them as required.
        """

        model_config = ConfigDict(extra="forbid", protected_namespaces=())

        num_seq_per_target: int = Field(ge=1)
        chains: str = Field(default="ALL")

    jobs_dir: Path
    proteinmpnn_dir: Path
    timeout_sec: int = Field(ge=1)
    enable_ui: bool
    ui_defaults: UiDefaults
    model_defaults: ModelDefaults


def load_config(path: Path) -> AppConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


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
    # chains can be "A" or ["A","B"] or "ALL".
    # Required: callers must explicitly provide it.
    chains: Union[str, List[str]]

    # ProteinMPNN args
    # Required: callers must explicitly provide it.
    num_seq_per_target: int = Field(
        validation_alias=AliasChoices("num_seq_per_target", "num_sequences", "Num_sequences"),
        serialization_alias="num_seq_per_target",
        ge=1,
    )
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
