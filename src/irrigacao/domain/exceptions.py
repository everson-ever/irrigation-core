"""Known application exceptions."""


class IrrigationError(Exception):
    """Base irrigation system error."""


class ValidationError(IrrigationError, ValueError):
    """Input data does not satisfy domain rules."""


class RecordNotFoundError(IrrigationError, LookupError):
    """Requested record does not exist."""


class HardwareError(IrrigationError, RuntimeError):
    """GPIO hardware could not be initialized or operated."""
