"""CLI della validazione e del catalogo dei controlli."""

import argparse
import json
from pathlib import Path

from sparql_analyzer.configuration.policy import CHECKS, DEFAULT_POLICY, Policy
from sparql_analyzer.static.validation import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", type=Path, nargs="?")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--policy", type=Path, help="Configurazione JSON checks/limits")
    parser.add_argument("--disable", action="append", default=[], metavar="CHECK")
    parser.add_argument("--enable", action="append", default=[], metavar="CHECK")
    parser.add_argument("--list-checks", action="store_true")
    args = parser.parse_args()
    try:
        policy = Policy.from_dict(json.loads(args.policy.read_text(encoding="utf-8-sig"))) if args.policy else DEFAULT_POLICY
        if set(args.disable) & set(args.enable):
            raise ValueError("Lo stesso controllo non puo essere abilitato e disabilitato")
        policy = policy.with_checks(**{name: False for name in args.disable},
                                    **{name: True for name in args.enable})
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.list_checks:
        print(json.dumps({name: {"enabled": policy.enabled(name), "description": check.description,
                                 "requires": check.requires, "default_enabled": check.default_enabled} for name, check in CHECKS.items()}, indent=2))
        return 0
    if args.query is None:
        parser.error("Specificare un file query oppure --list-checks")
    result = validate(args.query.read_text(encoding="utf-8-sig"), policy=policy)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
    return 0 if result["is_compliant"] else 1
