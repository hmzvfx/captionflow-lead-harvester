from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|authorization|credential|secret)(\s*[=:]\s*)([^\s,;]+)"),
]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            msg = pattern.sub(r"\1\2[REDACTED]", msg)
        record.msg = msg
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
