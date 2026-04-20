"""Exceptions used by payload_pipeline."""


class PayloadPipelineError(Exception):
    """Base exception for the package."""


class RegistryLookupError(PayloadPipelineError):
    """Raised when a game or marketplace is missing from the registry."""


class RegistryConflictError(PayloadPipelineError):
    """Raised when attempting to register a game slice that already exists."""


class SourceValidationError(PayloadPipelineError):
    """Raised when source input is incomplete for the requested mode."""
