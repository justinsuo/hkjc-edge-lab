"""Lightweight, consistent logging for the pipeline."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str = "hkjc") -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                              datefmt="%H:%M:%S")
        )
        root = logging.getLogger("hkjc")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
        _CONFIGURED = True
    return logging.getLogger(name if name.startswith("hkjc") else f"hkjc.{name}")
