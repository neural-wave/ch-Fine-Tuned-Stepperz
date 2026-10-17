"""One native Python log file per process, shared by workflow and test events."""
from datetime import datetime, timezone
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
import json
import logging
import os
from pathlib import Path
from threading import Lock
import time
from textwrap import indent

_handler = None
_lock = Lock()
active_workflow = ContextVar("active_workflow", default=None)


def backend_log_level():
    """Workflow owns INFO summaries; standalone adapters still log their output."""
    return logging.DEBUG if active_workflow.get() is not None else logging.INFO


def log_block(logger, title, content, *, level=logging.INFO):
    """Display text verbatim on separate lines; never reformat executable SPARQL."""
    if not logger.isEnabledFor(level):
        return
    if is_dataclass(content) and not isinstance(content, type):
        content = asdict(content)
    body = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2, default=str)
    divider = "-" * 72
    logger.log(level, "%s\n%s", title, indent(f"{divider}\n{body}\n{divider}", "    "))


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
                "%(asctime)s.%(msecs)03dZ | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S")
            formatter.converter = time.gmtime
            handler.setFormatter(formatter)
            root = logging.getLogger()
            root.setLevel(min(root.level, handler.level))
            root.addHandler(handler)
            _handler = handler
            logging.getLogger(__name__).info("Logging initialized file=%s", path)
        return Path(_handler.baseFilename)
