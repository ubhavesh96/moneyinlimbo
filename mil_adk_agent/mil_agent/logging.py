"""Logging helper (same shape as Andi's): one logger per module, level from LOG_LEVEL."""

import logging
import os


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return logging.getLogger(name)
