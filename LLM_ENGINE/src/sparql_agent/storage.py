"""Local artifacts. All run data lives under the ignored results directory."""

import json
from pathlib import Path

from .agent import RunResult


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_result(
    result: RunResult, directory: Path, *, jsonl: Path | None = None, metadata: dict | None = None
) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    data = result.to_dict()
    if metadata:
        data["benchmark"] = metadata
    base = directory / result.run_id
    record_path = base.with_suffix(".json")
    record_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths = {"record": str(record_path)}
    if result.generated_query:
        query_path = base.with_suffix(".rq")
        query_path.write_text(result.generated_query + "\n", encoding="utf-8")
        paths["query"] = str(query_path)
    append_jsonl(jsonl or directory / "runs.jsonl", data)
    return paths
