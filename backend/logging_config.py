import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from backend.config import LOG_LEVEL


def setup_logging():
    Path("data").mkdir(exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler("data/app.log", maxBytes=1_000_000, backupCount=3),
    ]
    logging.basicConfig(level=LOG_LEVEL, format=fmt, handlers=handlers, force=True)
