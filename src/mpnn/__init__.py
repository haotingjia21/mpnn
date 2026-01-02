"""ProteinMPNN mini-service wrapper.

Public surface area is kept intentionally small:

- `run_design(...)` for Kubeflow/K8s batch steps (path-based, writes artifacts)
- FastAPI factory in `mpnn.app.api:create_app`
"""

from .runner.design import run_design
from .core import CoreError, InputError, ExecutionError
from .core import DesignPayload, DesignResponse, DesignMetadata, DesignedSequence

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
