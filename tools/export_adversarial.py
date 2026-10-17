"""Esporta gli esiti dei casi singoli; non esegue SERVICE, update o dialetti."""

from tests.paths import FIXTURES, RESULTS

import json

from pyparsing import ParseBaseException
from rdflib.plugins.sparql.parser import parseQuery, parseUpdate

from sparql_analyzer.compliance import validate
from sparql_analyzer.parser import analyze, to_tree
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tools.generate_synthetic_data import generate


def export():
    root = FIXTURES
    corpus = root / "adversarial"
    output = RESULTS / "adversarial"
    output.mkdir(parents=True, exist_ok=True)
    report = []
    failures = 0
    for case in json.loads((corpus / "cases.json").read_text(encoding="utf-8")):
        query = (corpus / "queries" / case["file"]).read_text(encoding="utf-8")
        folder = output / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        item = {**case, "static_verdict": validate(query)}
        try:
            if case["kind"] == "update":
                trees = {"parse_tree": to_tree(parseUpdate(query))}
            else:
                parsed = to_tree(parseQuery(query))
                trees = {"parse_tree": parsed}
                try:
                    _, algebra, _ = analyze(query)
                    trees["algebra"] = algebra
                except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
                    item["algebra_status"] = "unsupported"
            for name, tree in trees.items():
                (folder / f"{name}.json").write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except ParseBaseException:
            if case["kind"] != "dialect":
                raise
            item["parser_status"] = "unsupported_dialect"
        if case["stage"] == "static":
            item["observed"] = "released" if item["static_verdict"]["is_compliant"] else "blocked"
        else:
            try:
                item["result"] = execute_checked(generate(), query)
                item["observed"] = "released"
            except ResultBlocked as error:
                item["observed"] = "blocked"
                item["reason_observed"] = str(error)
        item["test_passed"] = item["observed"] == case["expected"]
        failures += not item["test_passed"]
        (folder / "verdict.json").write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.append(item)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scenarios = json.loads((corpus / "scenarios.json").read_text(encoding="utf-8"))
    (output / "scenarios.json").write_text(json.dumps({
        "note": "Classificazione dei requisiti; esecuzione e lacune sono verificate da pytest, non da questo export.",
        "scenarios": scenarios,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Avversari singoli: {len(report) - failures}/{len(report)} esiti attesi; scenari multi-query verificati separatamente da pytest.")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if export() else 0)
