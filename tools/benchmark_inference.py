"""Compare agentic/prefetch latency with real backends and all static gates."""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from agent_orchestration import PromptRequest, SparqlWorkflow, StaticQueryAnalyzer
from agent_orchestration.adapters.laya import load_classifier
from agent_orchestration.local_models import CONFIG, open_generator
from agent_orchestration.logging_setup import configure_logging


def summarize(rows):
    measured = [row for row in rows if not row["warmup"]]
    accepted = [row for row in measured if row["outcome"]["status"] == "query_ready"]
    return {"runs": len(measured), "accepted": len(accepted),
            "statuses": dict(Counter(row["outcome"]["status"] for row in measured)),
            "median_seconds": median(row["seconds"] for row in measured) if measured else None,
            "accepted_median_seconds": median(row["seconds"] for row in accepted) if accepted else None}


async def benchmark(args):
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    directory = args.config.resolve().parent
    request = PromptRequest(args.prompt,
        args.schema_file.read_text(encoding="utf-8-sig") if args.schema_file else
        "SPHN clinical RDF. Retrieve class/property details from the schema MCP.",
        (args.policy_file or directory / "policy.txt").read_text(encoding="utf-8-sig"),
        (args.permissions_file or directory / "permissions.txt").read_text(encoding="utf-8-sig"))
    if not (config.get("mcp_url") or config.get("mcp_settings")):
        raise ValueError("Comparing retrieval modes requires MCP")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "label": args.label,
              "model": config["model"], "prompt": args.prompt,
              "semantic_validation": "not_checked; use tools.evaluate_workflow for fixture oracles",
              "server_options": "not_verified; record actual server launch command separately",
              "warmup_runs_per_mode": args.warmup, "modes": {}}
    started = perf_counter()
    guard = await load_classifier(args.config)
    report["classifier_load_seconds"] = perf_counter() - started
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for mode in args.modes:
        rows = []
        entry = {"runs": rows}
        report["modes"][mode] = entry
        try:
            started = perf_counter()
            async with open_generator(args.config, generation_mode=mode) as generator:
                entry["generator_open_seconds"] = perf_counter() - started
                workflow = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), model_timeout_seconds=args.timeout)
                for index in range(args.warmup + args.repeats):
                    started = perf_counter()
                    outcome = await workflow.run(request, execute=False)
                    rows.append({"warmup": index < args.warmup, "seconds": perf_counter() - started,
                                 "outcome": asdict(outcome)})
                    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as error:
            entry["error"] = {"type": type(error).__name__, "message": str(error)}
        entry["summary"] = summarize(rows)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--schema-file", type=Path)
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--permissions-file", type=Path)
    parser.add_argument("--modes", nargs="+", choices=["agentic", "prefetch"], default=["agentic", "prefetch"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--label", default="current-server")
    parser.add_argument("--out", type=Path, default=Path("artifacts/benchmarks/inference.json"))
    args = parser.parse_args()
    if args.repeats < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error("repeats/timeout must be positive and warmup nonnegative")
    configure_logging("benchmark-inference")
    report = asyncio.run(benchmark(args))
    print(json.dumps({mode: entry["summary"] for mode, entry in report["modes"].items()}, indent=2))
    print(f"Report: {args.out.resolve()}")
    return int(any(entry.get("error") or entry["summary"]["accepted"] != args.repeats
                   for entry in report["modes"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
