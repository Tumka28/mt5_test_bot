"""structlog setup — JSON output by default."""
from __future__ import annotations

import logging
import sys


def configure(level: str = "INFO", json: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json:
        try:
            import structlog  # type: ignore

            structlog.configure(
                processors=[
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.add_log_level,
                    structlog.processors.JSONRenderer(),
                ]
            )
            fmt = logging.Formatter("%(message)s")
        except Exception:
            fmt = logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
    else:
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
