"""python -m system_validation prepare|run --config system_validation/config.json"""
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
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--label", default="baseline", help="Strategy/model configuration label")
    parser.add_argument("--limit", type=int, help="Smoke subset; omitted uses every labeled prompt")
    parser.add_argument("--reset-patients", action="store_true", help="prepare only: explicitly clear patient graphs before loading the mock dataset")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    if args.reset_patients and args.command != "prepare":
        parser.error("reset-patients is only valid for prepare")
    config = read_config(args.config)
    configure_logging("system-validation")
    clients = Clients(config)
    try:
        if args.command == "prepare":
            receipt = prepare(config, clients, reset_patients=args.reset_patients)
            print(f"Ready: {len(receipt['sources']['patients'])} patient files; {config['receipt_file']}")
            return 0
        directory, report = run(config, clients, label=args.label, case_limit=args.limit)
        print(json.dumps(report["metrics"]["classification"], indent=2))
        logging.getLogger(__name__).info("Validation metrics: %s", json.dumps(report["metrics"], ensure_ascii=False))
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
