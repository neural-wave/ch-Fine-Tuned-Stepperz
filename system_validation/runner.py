"""Exercise the public API, then time eligible SELECTs on prepared Virtuoso."""
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter

from sparql_analyzer.validation import validate
from .metrics import summarize
from .settings import load_cases
from .virtuoso import ready

logger = logging.getLogger(__name__)


def trial(case, clients, config, *, index, warmup, api_only=False):
    started = perf_counter()
    logger.info("Case started id=%s repeat=%s warmup=%s prompt=%r", case["id"], index, warmup, case["prompt"])
    row = _trial(case, clients, config, index=index, warmup=warmup, api_only=api_only)
    row["total_seconds"] = perf_counter() - started
    predicted = row["predicted_malicious"]
    row["correct"] = predicted == case["malicious"] if predicted is not None else None
    decision = row.get("response", {}).get("analytics", {}).get("prompt_decision")
    row["prompt_decision"] = decision
    row["prompt_predicted_malicious"] = decision != "allow" if decision in {"allow", "block", "review"} else None
    row["prompt_correct"] = (row["prompt_predicted_malicious"] == case["malicious"]
                             if row["prompt_predicted_malicious"] is not None else None)
    row["outcome"] = ("error" if predicted is None else
                      ("tp" if predicted else "fn") if case["malicious"] else ("fp" if predicted else "tn"))
    tokens = row.get("response", {}).get("tokens_consumed")
    row["effective_total_tokens_per_second"] = tokens / row["api_seconds"] if tokens is not None and row["api_seconds"] > 0 else None
    logger.info("Case completed %s", json.dumps(row, ensure_ascii=False))
    return row


def _trial(case, clients, config, *, index, warmup, api_only):
    row = {**case, "repeat": index, "warmup": warmup, "predicted_malicious": None,
           "execution": {"status": "not_eligible", "seconds": []}}
    started = perf_counter()
    try:
        response, seconds = clients.translate(case["prompt"])
        row.update(response=response, api_seconds=seconds,
                   predicted_malicious=not response["is_compliant"])
    except Exception as error:
        logger.exception("API request failed id=%s", case["id"])
        row.update(api_seconds=perf_counter() - started,
                   error={"type": type(error).__name__, "message": str(error)})
        return row
    # Labels are held by the evaluator, never sent to the API. No query from a
    # malicious labeled prompt is executed, including false negative approvals.
    if api_only:
        row["execution"]["status"] = "disabled"
        return row
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
        logger.exception("Query execution failed id=%s", case["id"])
        execution.update(status="error", error={"type": type(error).__name__, "message": str(error)})
    return row


def save_summary(directory, rows, metadata):
    report = {"metadata": metadata, "metrics": summarize(rows)}
    (directory / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "metrics.log").write_text(json.dumps(report["metrics"], ensure_ascii=False, indent=2), encoding="utf-8")
    import csv
    with (directory / "trials.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["id", "prompt", "category", "repeat", "warmup", "malicious", "predicted_malicious", "correct", "outcome",
                  "prompt_decision", "prompt_predicted_malicious", "prompt_correct",
                  "api_seconds", "total_seconds", "tokens_consumed", "effective_total_tokens_per_second", "execution_status", "error"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{key: row.get(key) for key in fields},
                "tokens_consumed": row.get("response", {}).get("tokens_consumed"),
                "execution_status": row["execution"]["status"]})
    return report


def run(config, clients, *, label="baseline", case_limit=None, api_only=False):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = config["out_dir"] / timestamp
    directory.mkdir(parents=True, exist_ok=False)
    handler = logging.FileHandler(directory / "execution.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    package_logger = logging.getLogger("system_validation")
    previous_level = package_logger.level
    package_logger.setLevel(logging.INFO)
    package_logger.addHandler(handler)
    try:
        return _run(config, clients, label=label, case_limit=case_limit, api_only=api_only,
                    timestamp=timestamp, directory=directory)
    except BaseException:
        logger.exception("Validation interrupted or could not complete")
        raise
    finally:
        package_logger.removeHandler(handler)
        handler.close()
        package_logger.setLevel(previous_level)


def _run(config, clients, *, label, case_limit, api_only, timestamp, directory):
    started = perf_counter()
    paths = config.get("cases_files") or [config["cases_file"]]
    payload = load_cases(paths)
    cases = payload["cases"][:case_limit] if case_limit is not None else payload["cases"]
    if not cases:
        raise ValueError("No validation cases selected")
    # Fail before model calls if the full configured sources were not loaded.
    receipt = None if api_only else ready(config, clients)
    metadata = {"created_at": timestamp, "strategy_label": label, "dataset_annotation": payload.get("annotation"),
        "case_sources": [{"file": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path in paths],
        "selected_cases": len(cases), "available_cases": len(payload["cases"]), "api_only": api_only,
        "config": json.loads(json.dumps(config, default=str)),
        "load_receipt_sha256": hashlib.sha256(config["receipt_file"].read_bytes()).hexdigest() if receipt else None,
        "loaded_patient_files": len(receipt["sources"]["patients"]) if receipt else None,
        "loaded_ontology_files": len(receipt["sources"]["ontologies"]) if receipt else None,
        "positive_class": "malicious", "prediction": "not API.is_compliant (end-to-end verdict)",
        "oracle": "Dataset malicious/compliant labels only; no query reference or semantic-equivalence score",
        "throughput_note": "Effective output tokens per stage wall time includes retrieval/prefill; not decoder tokens/s or TTFT",
        "classification_note": "Accuracy includes API errors as failures; confusion matrix/precision/recall use valid verdicts. Coverage and per-class all-attempt rates expose errors.",
        "database_note": "Source hashes plus loader/graph inventory, not a transactional snapshot. Keep the database isolated from writers.",
        "status": "running"}
    if receipt:
        (directory / "load-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    (directory / "cases.json").write_text(json.dumps(payload | {"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Validation started cases=%s label=%s api_only=%s", len(cases), label, api_only)
    rows = []
    save_summary(directory, rows, metadata)
    try:
        with (directory / "trials.jsonl").open("w", encoding="utf-8") as stream:
            for index in range(config["warmup"]):
                row = trial(cases[index % len(cases)], clients, config, index=index, warmup=True, api_only=api_only)
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
            for case in cases:
                for index in range(config["repeats"]):
                    print(f"{case['id']} [{index + 1}/{config['repeats']}]", flush=True)
                    row = trial(case, clients, config, index=index, warmup=False, api_only=api_only)
                    rows.append(row)
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    save_summary(directory, rows, metadata)
        if not api_only:
            ready(config, clients)
        metadata["status"] = "complete"
    except BaseException as error:
        metadata.update(status="invalid_or_interrupted", error={"type": type(error).__name__, "message": str(error)})
        metadata["elapsed_seconds"] = perf_counter() - started
        save_summary(directory, rows, metadata)
        raise
    metadata["elapsed_seconds"] = perf_counter() - started
    report = save_summary(directory, rows, metadata)
    logger.info("Validation metrics %s", json.dumps(report["metrics"], ensure_ascii=False))
    return directory, report
