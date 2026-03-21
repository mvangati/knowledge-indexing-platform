"""Structured JSON logger with correlation-ID support."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from src.config import get_settings


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    settings = get_settings()
    effective_level = level or settings.log_level

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(getattr(logging, effective_level.upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger
