"""Small in-memory application-log tail used by user error reports.

The buffer intentionally contains only formatted log records. Application
code never logs request bodies, SQL parameters, OTPs, passwords, JWTs, or
patient identity, and the redaction below is a second line of defence for
provider/HTTP error text that might echo a header.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from threading import Lock

_CAPACITY = 500
_MAX_LINE = 1200
_redact = re.compile(
    r"(?i)(authorization|access_token|password|secret|api[_-]?key)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


class _RingBufferHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: deque[str] = deque(maxlen=_CAPACITY)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            request_id = getattr(record, "request_id", None)
            prefix = (
                f"{record.levelname} {record.name}"
                + (f" request_id={request_id}" if request_id else "")
            )
            line = f"{prefix}: {message}"
            line = _redact.sub(r"\1\2[REDACTED]", line)
            if len(line) > _MAX_LINE:
                line = line[:_MAX_LINE] + "…"
            with self._lock:
                self.records.append(line)
        except Exception:  # pragma: no cover - logging must never crash
            self.handleError(record)


_handler = _RingBufferHandler()
_install_lock = Lock()
_installed = False


def install_log_buffer() -> None:
    """Attach the ring buffer to the root logger exactly once."""
    global _installed
    with _install_lock:
        if _installed:
            return
        root = logging.getLogger()
        if _handler not in root.handlers:
            root.addHandler(_handler)
        _installed = True


def recent_logs(limit: int = 200) -> str:
    """Return the newest formatted log lines, oldest first."""
    bounded = max(1, min(int(limit), _CAPACITY))
    with _handler._lock:
        lines = list(_handler.records)[-bounded:]
    return "\n".join(lines)
