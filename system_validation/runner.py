"""Exercise the public API, then time eligible SELECTs on prepared Virtuoso."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter

from sparql_analyzer.validation import validate
from .metrics import summarize
from .settings import load_cases
from .virtuoso import ready


def trial(case, clients, config, *, index, warmup):
    row = {**case, "repeat": index, "warmup": warmup, "predicted_malicious": None,
           "execution": {"status": "not_eligible", "seconds": []}}
    started = perf_counter()
    try:
        response, seconds = clients.translate(case["prompt"])
        row.update(response=response, api_seconds=seconds,
                   predicted_malicious=not response["is_compliant"])
    except Exception as error:
        row.update(api_seconds=perf_counter() - started,
                   error={"type": type(error).__name__, "message": str(error)})
        return row
    # Labels are held by the evaluator, never sent to the API. No query from a
    # malicious labeled prompt is executed, including false negative approvals.
    if case["malicious"] or not response["is_compliant"] or warmup:
        return row
    execution = row["execution"]
    try:
        query = response["sparql_query"]
        if validate(query)["is_compliant"] is not True:
            execution["status"] = "rejected_locally"
            return row
        result, elapsed = clients.query(query)
        execution.update(status="executed", warmup_seconds=elapsed,
                         result_columns=result["head"]["vars"], result_rows=len(result["results"]["bindings"]))
        execution["first_result_sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        for _ in range(config["query_repeats"]):
            result, elapsed = clients.query(query)
            execution["seconds"].append(elapsed)
    except Exception as error:
        execution.update(status="error", error={"type": type(error).__name__, "message": str(error)})
    return row


def save_summary(directory, rows, metadata):
    report = {"metadata": metadata, "metrics": summarize(rows)}
    (directory / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "metrics.log").write_text(json.dumps(report["metrics"], ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run(config, clients, *, label="baseline", case_limit=None):
    payload = load_cases(config["cases_file"])
    cases = payload["cases"][:case_limit] if case_limit is not None else payload["cases"]
    if not cases:
        raise ValueError("No validation cases selected")
    # Fail before model calls if the full configured sources were not loaded.
    receipt = ready(config, clients)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = config["out_dir"] / timestamp
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {"created_at": timestamp, "strategy_label": label, "dataset_annotation": payload.get("annotation"),
        "cases_sha256": hashlib.sha256(Path(config["cases_file"]).read_bytes()).hexdigest(),
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in config.items()},
        "load_receipt_sha256": hashlib.sha256(config["receipt_file"].read_bytes()).hexdigest(),
        "loaded_patient_files": len(receipt["sources"]["patients"]), "loaded_ontology_files": len(receipt["sources"]["ontologies"]),
        "positive_class": "malicious", "prediction": "not API.is_compliant (end-to-end verdict)",
        "oracle": "Manual malicious labels only; no query reference or semantic-equivalence score",
        "throughput_note": "Effective output tokens per stage wall time includes retrieval/prefill; not decoder tokens/s or TTFT",
        "classification_note": "Accuracy includes API errors as failures; confusion matrix/precision/recall use valid verdicts. Coverage and per-class all-attempt rates expose errors.",
        "database_note": "Source hashes plus loader/graph inventory, not a transactional snapshot. Keep the database isolated from writers.",
        "status": "running"}
    (directory / "load-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    rows = []
    try:
        with (directory / "trials.jsonl").open("w", encoding="utf-8") as stream:
            for index in range(config["warmup"]):
                row = trial(cases[index % len(cases)], clients, config, index=index, warmup=True)
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
            for case in cases:
                for index in range(config["repeats"]):
                    print(f"{case['id']} [{index + 1}/{config['repeats']}]", flush=True)
                    row = trial(case, clients, config, index=index, warmup=False)
                    rows.append(row)
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    save_summary(directory, rows, metadata)
        ready(config, clients)
        metadata["status"] = "complete"
    except BaseException as error:
        metadata.update(status="invalid_or_interrupted", error={"type": type(error).__name__, "message": str(error)})
        save_summary(directory, rows, metadata)
        raise
    report = save_summary(directory, rows, metadata)
    # Small scalar table for comparing multiple strategy labels without reading JSONL.
    import csv
    with (directory / "trials.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["id", "repeat", "warmup", "malicious", "predicted_malicious", "api_seconds", "tokens_consumed", "execution_status"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{key: row.get(key) for key in fields[:6]},
                "tokens_consumed": row.get("response", {}).get("tokens_consumed"),
                "api_seconds": row["api_seconds"], "execution_status": row["execution"]["status"]})
    return directory, report
