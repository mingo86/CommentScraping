"""Logger utility."""
import logging
import sys


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s — %(message)s",
            datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)
        
        # File log
        file_handler = logging.FileHandler("monitor.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s — %(message)s"
        ))
        logger.addHandler(file_handler)
    logger.setLevel(level)
    return logger
