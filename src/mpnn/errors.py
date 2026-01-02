from __future__ import annotations


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
