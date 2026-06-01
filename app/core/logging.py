"""Minimal, dependency-free logging setup.

Call `configure_logging()` once at startup. Modules then use the standard
`logging.getLogger(__name__)` pattern.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers when uvicorn reloads the module.
    root.handlers = [handler]

    # Tame noisy third-party loggers.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
