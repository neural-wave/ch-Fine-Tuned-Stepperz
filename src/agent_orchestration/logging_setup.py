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


def configure_logging(label="workflow", *, console=False) -> Path:
    """Add a file handler once without replacing the caller's logging handlers."""
    global _handler
    with _lock:
        root = logging.getLogger()
        created = False
        if (_handler is None or _handler.stream is None
                or getattr(_handler, "_sparql_pid", None) != os.getpid()):
            resume = _handler is not None and getattr(_handler, "_sparql_pid", None) == os.getpid()
            previous_path = Path(_handler.baseFilename) if resume else None
            if _handler is not None:
                for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
                    logging.getLogger(name).removeHandler(_handler)
                _handler.close()
            directory = Path(os.getenv("SPARQL_LOG_DIR",
                str(Path(__file__).resolve().parents[2] / "artifacts/logs")))
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            path = previous_path if resume else directory / f"{label}-{stamp}-{os.getpid()}.log"
            handler = logging.FileHandler(path, mode="a" if resume else "x", encoding="utf-8")
            level = os.getenv("SPARQL_LOG_LEVEL", "INFO").upper()
            handler.setLevel(level)
            formatter = logging.Formatter(
                "%(asctime)s.%(msecs)03dZ | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S")
            formatter.converter = time.gmtime
            handler.setFormatter(formatter)
            handler._sparql_pid = os.getpid()
            _handler = handler
            created = True
        root.setLevel(min(root.level, _handler.level))
        if _handler not in root.handlers:
            root.addHandler(_handler)
        # Uvicorn intentionally stops propagation for its own console logs.
        # Attach at those boundaries only, so each event reaches the file once.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            target = logging.getLogger(name)
            if not target.propagate and _handler not in target.handlers:
                target.addHandler(_handler)
            elif target.propagate and _handler in target.handlers:
                target.removeHandler(_handler)
        if console and not any(isinstance(item, logging.StreamHandler)
                               and not isinstance(item, logging.FileHandler) for item in root.handlers):
            terminal = logging.StreamHandler()
            terminal.setLevel(_handler.level)
            terminal.setFormatter(_handler.formatter)
            root.addHandler(terminal)
        if created:
            logging.getLogger(__name__).info("Logging initialized file=%s", path)
        return Path(_handler.baseFilename)
