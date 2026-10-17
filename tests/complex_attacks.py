"""Esecuzione delle sonde complesse, solo su fixture fittizie locali."""

import json
from pathlib import Path
from decimal import Decimal

from rdflib import Literal, URIRef, XSD

from sparql_analyzer.compliance import validate
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from sparql_analyzer.parser import analyze
from tests.complex_fixture import complex_cohort
from tests.generate_synthetic_data import SPHN, SYN

ROOT = Path(__file__).parent / "adversarial_complex"
CASES = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))


def prepare(case):
    query = (ROOT / "queries" / case["file"]).read_text(encoding="utf-8")
    dataset = complex_cohort()
    if case["recipe"] == "duplicate_person":
        for graph in dataset.contexts():
            for subject, predicate, _ in list(graph.triples((None, SPHN.hasSubjectPseudoIdentifier, None))):
                graph.set((subject, predicate, SYN["one-complex-person"]))
    elif case["recipe"] == "non_finite":
        dataset.graph(URIRef("http://example.org/graph/complex-0")).set(
            (SYN["complex-quantity-0"], SPHN.hasValue, Literal("NaN", datatype=XSD.double))
        )
    return dataset, query


def observe(case):
    dataset, query = prepare(case)
    verdict = validate(query)
    observation = {"static_verdict": verdict}
    if not verdict["is_compliant"]:
        return {**observation, "observed": "blocked_static"}
    try:
        result = execute_checked(dataset, query)
        return {**observation, "observed": "released", "result": result}
    except ResultBlocked as error:
        return {**observation, "observed": "blocked_runtime", "reason": str(error)}
    except Exception as error:
        # Un crash non e un rifiuto controllato. Il test lo segnala come errore.
        return {**observation, "observed": "controller_error", "error_type": type(error).__name__}


def export():
    output = ROOT.parent / "results/adversarial_complex"
    output.mkdir(parents=True, exist_ok=True)
    report = []
    for case in CASES:
        item = {**case, **observe(case)}
        query = (ROOT / "queries" / case["file"]).read_text(encoding="utf-8")
        syntax, algebra, _ = analyze(query)
        folder = output / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for name, tree in (("parse_tree", syntax), ("algebra", algebra)):
            (folder / (name + ".json")).write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if case["expected"] == "blocked":
            item["matches_observation"] = item["observed"] in {"blocked_static", "blocked_runtime"}
        else:
            value = item.get("result", {}).get("results", {}).get("bindings", [{}])[0].get("summary", {}).get("value")
            item["matches_observation"] = item["observed"] == "released" and value is not None and Decimal(value) == Decimal(case["expected_value"])
        item["privacy_bypass_reproduced"] = case["expected"] == "leak" and item["matches_observation"]
        (folder / "verdict.json").write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.append(item)
        print(case["id"], item["observed"], "atteso:", case["expected"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = export()
    raise SystemExit(1 if any(not item["matches_observation"] for item in report) else 0)
