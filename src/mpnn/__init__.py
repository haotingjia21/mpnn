"""ProteinMPNN mini-service wrapper.

Public surface area is kept intentionally small:

- `run_design(...)` for Kubeflow/K8s batch steps (path-based, writes artifacts)
- FastAPI app in `mpnn.api:app`
"""

from .design import run_design
from .errors import CoreError, InputError, ExecutionError
from .schemas import DesignPayload, DesignResponse, DesignMetadata, DesignedSequence

__all__ = [
    "run_design",
    "CoreError",
    "InputError",
    "ExecutionError",
    "DesignPayload",
    "DesignResponse",
    "DesignMetadata",
    "DesignedSequence",
]
