"""One native Python log file per process, shared by workflow and test events."""
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from threading import Lock
import time

_handler = None
_lock = Lock()


def configure_logging(label="workflow") -> Path:
    """Add a file handler once without replacing the caller's logging handlers."""
    global _handler
    with _lock:
        if _handler is None:
            directory = Path(os.getenv("SPARQL_LOG_DIR",
                str(Path(__file__).resolve().parents[2] / "artifacts/logs")))
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            path = directory / f"{label}-{stamp}-{os.getpid()}.log"
            handler = logging.FileHandler(path, mode="x", encoding="utf-8")
            level = os.getenv("SPARQL_LOG_LEVEL", "INFO").upper()
            handler.setLevel(level)
            formatter = logging.Formatter(
                "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S")
            formatter.converter = time.gmtime
            handler.setFormatter(formatter)
            root = logging.getLogger()
            root.setLevel(min(root.level, handler.level))
            root.addHandler(handler)
            _handler = handler
            logging.getLogger(__name__).info("Logging initialized file=%s", path)
        return Path(_handler.baseFilename)
