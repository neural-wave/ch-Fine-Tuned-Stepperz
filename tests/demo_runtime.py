"""Esegue scenari runtime sul file di pazienti sintetici gia generato."""

import json
from pathlib import Path

from rdflib import Dataset

from sparql_analyzer.demo import EXAMPLE_QUERY
from sparql_analyzer.runtime import ResultBlocked, execute_checked


def main():
    root = Path(__file__).parent
    path = root / "data/synthetic/cohort.trig"
    if not path.is_file():
        raise SystemExit("Prima eseguire: uv run python -m tests.generate_synthetic_data")
    dataset = Dataset()
    dataset.parse(path, format="trig")
    scenarios = [
        ("coorte_sufficiente", EXAMPLE_QUERY),
        ("singolo_paziente", EXAMPLE_QUERY.replace("BilledDiagnosis", "OncologyDiagnosis")),
        ("dieci_esami_un_paziente", EXAMPLE_QUERY.replace("COUNT(DISTINCT ?g)", "COUNT(?diagnosis)").replace("BilledDiagnosis", "LabTestEvent")),
        ("identificatori_in_chiaro", """PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
        SELECT ?id WHERE { GRAPH ?g { ?subject sphn:hasIdentifier ?id } }"""),
    ]
    report = []
    for name, query in scenarios:
        try:
            result = execute_checked(dataset, query, min_patients=5)
            item = {"scenario": name, "status": "released", "result": result}
            count = result["results"]["bindings"][0]["patients"]["value"]
            print(f"{name}: CONSENTITO, patients = {count}")
        except ResultBlocked as error:
            item = {"scenario": name, "status": "blocked", "reason": str(error)}
            print(f"{name}: BLOCCATO, {error}")
        report.append(item)
    output = root / "results/runtime-demo.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
