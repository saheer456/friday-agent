"""Request tracing context - propagates trace_id across async boundaries."""
import contextvars
import logging
import uuid
from typing import Optional
from contextvars import Token

logger = logging.getLogger("Tracing")

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """Get the current trace_id, generating one if not set."""
    tid = trace_id_var.get()
    if not tid:
        tid = str(uuid.uuid4())
        trace_id_var.set(tid)
    return tid


def set_trace_id(trace_id: Optional[str] = None) -> Token[str]:
    """Set a trace_id for the current context. Generates one if None.
    Returns a token for resetting the contextvar."""
    tid = trace_id or str(uuid.uuid4())
    return trace_id_var.set(tid)


class TraceLogger:
    """Logger wrapper that includes the current trace_id."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _extend(self, msg: str) -> str:
        tid = get_trace_id()
        if tid:
            return f"[trace={tid[:8]}] {msg}"
        return msg

    def debug(self, msg: str, *args, **kwargs):
        self._logger.debug(self._extend(msg), *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._logger.info(self._extend(msg), *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._logger.warning(self._extend(msg), *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._logger.error(self._extend(msg), *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        self._logger.exception(self._extend(msg), *args, **kwargs)

    @property
    def wrapped(self) -> logging.Logger:
        return self._logger