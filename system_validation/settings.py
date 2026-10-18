"""One JSON configuration; paths are relative to the repository root."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "system_validation/config.json"


def read_config(path=DEFAULT_CONFIG):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    for key in ("patients_dir", "ontologies_dir", "ontology_cache_dir", "receipt_file", "out_dir"):
        config[key] = (ROOT / config[key]).resolve()
    if "cases_files" in config:
        config["cases_files"] = [(ROOT / value).resolve() for value in config["cases_files"]]
    else:
        config["cases_file"] = (ROOT / config["cases_file"]).resolve()
    for key in ("repeats", "query_repeats", "timeout_seconds"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if type(config["warmup"]) is not int or config["warmup"] < 0:
        raise ValueError("warmup must be a nonnegative integer")
    return config


def load_cases(path):
    if isinstance(path, (list, tuple)):
        merged, annotations = {}, []
        for source in path:
            payload = load_cases(source)
            annotations.append(payload.get("annotation"))
            for row in payload["cases"]:
                key = row["prompt"].strip()
                provenance = {"file": str(source), "id": row["id"]}
                if key in merged:
                    if merged[key]["malicious"] != row["malicious"]:
                        raise ValueError(f"Conflicting labels for prompt: {row['prompt']!r}")
                    merged[key]["sources"].append(provenance)
                else:
                    case_id = row["id"] if len(path) == 1 else f"{Path(source).stem}:{row['id']}"
                    merged[key] = {**row, "id": case_id, "sources": [provenance]}
        cases = list(merged.values())
        if not cases or len({row["id"] for row in cases}) != len(cases):
            raise ValueError("Empty merged dataset or duplicate case IDs")
        return {"version": 1, "annotation": annotations, "cases": cases}
    if Path(path).suffix == ".jsonl":
        rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if any(type(row.get("compliant")) is not bool for row in rows):
            raise ValueError("Every benchmark prompt needs a boolean compliant label")
        payload = {"version": 1, "annotation": "Benchmark compliant labels mapped to malicious = not compliant.",
                   "cases": [{"id": row["id"], "prompt": row["question"], "malicious": not row["compliant"],
                              "category": row.get("category", "uncategorized"),
                              "difficulty": row.get("difficulty"), "expected_reason": row.get("why_non_compliant"),
                              "reference_query": row.get("reference")}
                             for row in rows]}
    else:
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
