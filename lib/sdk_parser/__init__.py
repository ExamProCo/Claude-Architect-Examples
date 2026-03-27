from .formatter import format_message
from . import logger as _logger


def log_message(message) -> str:
    """Format a message, write it to the run's log file, and return the formatted string."""
    formatted = format_message(message)
    _logger.write(formatted)
    return formatted


__all__ = ["format_message", "log_message"]
