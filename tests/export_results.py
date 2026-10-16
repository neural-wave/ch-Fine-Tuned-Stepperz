"""Verifica il parsing dei casi e genera gli alberi, senza eseguire query."""

import json
from pathlib import Path

from rdflib.plugins.sparql.parser import parseUpdate

from sparql_analyzer.parser import analyze, to_tree
from sparql_analyzer.compliance import validate


def main():
    root = Path(__file__).resolve().parent / "cases"
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    results = root.parent / "results"
    results.mkdir(parents=True, exist_ok=True)
    failures = 0
    report = []
    for case in cases:
        verdict = None
        try:
            query = (root / case["file"]).read_text(encoding="utf-8")
            output = results / Path(case["file"]).stem
            output.mkdir(parents=True, exist_ok=True)
            if case["kind"] == "update":
                trees = {"parse_tree": to_tree(parseUpdate(query))}
            else:
                syntax, algebra, _ = analyze(query)
                trees = {"parse_tree": syntax, "algebra": algebra}
            for name, tree in trees.items():
                (output / f"{name}.json").write_text(
                    json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            verdict = validate(query)
            (output / "compliance.json").write_text(
                json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            if verdict["is_compliant"] != case["expected_compliant"]:
                raise AssertionError("Verdetto diverso dall'atteso")
            missing = set(case["expected_violations"]) - set(verdict["violations"])
            if missing:
                raise AssertionError(f"Regole non riconosciute: {sorted(missing)}")
            status = "OK"
        except Exception as error:
            status = f"ERROR: {error}"
            failures += 1
        expected = ", ".join(case["expected_violations"]) or "conforme"
        print(f"{case['file']}: test {status}; atteso: {expected}")
        report.append({**case, "test_status": status, "actual": verdict})
    (results / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{len(cases) - failures}/{len(cases)} casi verificati dal validatore.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
