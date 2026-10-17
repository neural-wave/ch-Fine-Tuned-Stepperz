"""Demo locale: query SPARQL -> parse tree -> algebra -> risultato su fixture."""

import argparse
import json
import sys
from pathlib import Path

from pyparsing import ParseBaseException
from rdflib import Dataset, Namespace, RDF, URIRef

from sparql_analyzer.parsing.parser import analyze


SPHN = Namespace("https://biomedit.ch/rdf/sphn-schema/sphn#")
EXAMPLE_QUERY = """PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT (COUNT(DISTINCT ?g) AS ?patients)
WHERE {
  GRAPH ?g { ?diagnosis a sphn:BilledDiagnosis . }
  FILTER(STRSTARTS(STR(?g), "http://example.org/graph/"))
}
"""


def demo_dataset():
    dataset = Dataset()
    # Due diagnosi per il primo paziente: COUNT DISTINCT deve contarlo una volta.
    for patient, diagnoses in (("patient-1", 2), ("patient-2", 1)):
        graph = dataset.graph(URIRef(f"http://example.org/graph/{patient}"))
        for index in range(diagnoses):
            graph.add((URIRef(f"urn:{patient}:diagnosis:{index}"), RDF.type, SPHN.BilledDiagnosis))
    dataset.graph(URIRef("http://example.org/graph/patient-3")).add(
        (URIRef("urn:patient-3:lab"), RDF.type, SPHN.LabTestEvent)
    )
    dataset.graph(URIRef("urn:ontology")).add(
        (URIRef("urn:ontology:diagnosis"), RDF.type, SPHN.BilledDiagnosis)
    )
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", type=Path, help="File .rq SPARQL 1.1 da analizzare")
    parser.add_argument("--out", type=Path, help="Directory per parse_tree.json e algebra.json")
    args = parser.parse_args()
    try:
        query = args.query.read_text(encoding="utf-8-sig") if args.query else EXAMPLE_QUERY
        syntax, algebra, prepared = analyze(query)
        print("QUERY\n" + query)
        for name, tree in (("parse_tree", syntax), ("algebra", algebra)):
            encoded = json.dumps(tree, ensure_ascii=False, indent=2)
            print(f"\n{name.upper()}\n{encoded}")
            if args.out:
                args.out.mkdir(parents=True, exist_ok=True)
                (args.out / f"{name}.json").write_text(encoded + "\n", encoding="utf-8")
        if not args.query:
            result = list(demo_dataset().query(prepared))
            count = int(result[0][0])
            if count != 2:
                raise RuntimeError(f"Conteggio inatteso: {count}, atteso 2")
            print(f"\nTEST OK: patients = {count} (atteso: 2)")
        return 0
    except ParseBaseException as error:
        print(f"Errore SPARQL alla riga {error.lineno}, colonna {error.col}: {error.msg}\n"
              "Il parser supporta SPARQL standard, non DEFINE o OPTION(inference) di Virtuoso.",
              file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        print(f"Errore: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
