"""Rebuild diagnostic reports from saved trials without contacting services."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .diagnostics import diagnose
from .runner import save_summary
from .settings import load_cases


def rebuild(config, trials):
    source = Path(trials).resolve()
    raw = source.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    if not rows:
        raise ValueError("No saved trials found")
    cases = load_cases(config.get("cases_files") or [config["cases_file"]])["cases"]
    references = {case["prompt"].strip(): case.get("reference_query") for case in cases}
    for row in rows:
        if not row.get("reference_query"):
            row["reference_query"] = references.get(row["prompt"].strip())
        row["diagnostics"] = diagnose(row)
    directory = config["out_dir"] / ("report-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {"mode": "offline_reanalysis", "source": str(source),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "reference_sources": [{"file": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                    for path in config.get("cases_files") or [config["cases_file"]]],
                "note": "Original trials unchanged. Missing historical telemetry cannot be recovered. Local rechecks use the current checker and default policy."}
    (directory / "trials.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return directory, save_summary(directory, rows, metadata)
