"""python -m system_validation check|prepare|run --config system_validation/config.json"""
import argparse
import json
import logging
import sys

from agent_orchestration.logging_setup import configure_logging

from .client import Clients
from .runner import run
from .settings import DEFAULT_CONFIG, read_config
from .virtuoso import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "prepare", "run"])
    parser.add_argument("--inference", action="store_true", help="check only: run one real API translation including Laya and generator")
    parser.add_argument("--with-virtuoso", action="store_true", help="check only: verify loaded data and preparation receipt")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--label", default="baseline", help="Strategy/model configuration label")
    parser.add_argument("--limit", type=int, help="Smoke subset; omitted uses every labeled prompt")
    parser.add_argument("--api-only", action="store_true", help="run only: evaluate classification and resources without Virtuoso")
    parser.add_argument("--cases", action="append", help="run only: JSON/JSONL dataset; repeat to merge files")
    parser.add_argument("--reset-patients", action="store_true", help="prepare only: explicitly clear patient graphs before loading the mock dataset")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    if args.reset_patients and args.command != "prepare":
        parser.error("reset-patients is only valid for prepare")
    if (args.api_only or args.cases) and args.command != "run":
        parser.error("api-only and cases are only valid for run")
    if (args.inference or args.with_virtuoso) and args.command != "check":
        parser.error("inference and with-virtuoso are only valid for check")
    config = read_config(args.config)
    if args.cases:
        from pathlib import Path
        config["cases_files"] = [Path(value).resolve() for value in args.cases]
    configure_logging("system-validation")
    clients = Clients(config)
    try:
        if args.command == "check":
            from .health import check
            report = check(config, clients, inference=args.inference, with_virtuoso=args.with_virtuoso)
            return 0 if report["ok"] else 1
        if args.command == "prepare":
            receipt = prepare(config, clients, reset_patients=args.reset_patients)
            print(f"Ready: {len(receipt['sources']['patients'])} patient files; {config['receipt_file']}")
            return 0
        directory, report = run(config, clients, label=args.label, case_limit=args.limit, api_only=args.api_only)
        print(json.dumps(report["metrics"]["classification"], indent=2))
        print("Prompt guard:")
        print(json.dumps(report["metrics"]["prompt_guard"], indent=2))
        print(f"Report: {directory}")
        # Scores and individual request failures are observations, never gates.
        return 0
    except Exception as error:
        logging.getLogger(__name__).exception("Validation could not complete")
        print(f"Validation could not complete: {error}", file=sys.stderr)
        return 2
    finally:
        clients.close()


if __name__ == "__main__":
    raise SystemExit(main())
