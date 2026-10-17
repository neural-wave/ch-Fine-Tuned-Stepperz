"""One JSON configuration; paths are relative to the repository root."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "system_validation/config.json"


def read_config(path=DEFAULT_CONFIG):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    for key in ("patients_dir", "ontologies_dir", "ontology_cache_dir", "cases_file", "receipt_file", "out_dir"):
        config[key] = (ROOT / config[key]).resolve()
    for key in ("repeats", "query_repeats", "timeout_seconds"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if type(config["warmup"]) is not int or config["warmup"] < 0:
        raise ValueError("warmup must be a nonnegative integer")
    return config


def load_cases(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("version") != 1:
        raise ValueError("Unsupported validation dataset version")
    cases = payload["cases"]
    if not cases or len({row["id"] for row in cases}) != len(cases):
        raise ValueError("Empty dataset or duplicate case IDs")
    for row in cases:
        if not row["id"] or not isinstance(row["prompt"], str) or not row["prompt"].strip():
            raise ValueError("Every case needs an ID and nonempty prompt")
        if type(row.get("malicious")) is not bool:
            raise ValueError("Every prompt needs a boolean malicious label")
    return payload
