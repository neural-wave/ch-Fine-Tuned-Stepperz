"""Verifica gli esempi numerici della guida docs/architettura.md."""

import json
from decimal import Decimal

from rdflib import Dataset, Literal, Namespace, URIRef

from sparql_analyzer import ExecutionContext, Policy, ReleaseHistory
from sparql_analyzer.runtime import ResultBlocked, execute_checked


SPHN = Namespace("https://biomedit.ch/rdf/sphn-schema/sphn#")
PREFIX = f"PREFIX sphn: <{SPHN}>\n"
# Esempi di provenienza/privacy con dati minimali, non una demo SHACL.
HARDENED = Policy.hardened().with_checks(privacy_normalize_errors=False, adequacy_shacl=False)
MEAN = PREFIX + """SELECT (AVG(?patientAverage) AS ?cohortAverage)
WHERE {
  { SELECT (AVG(?value) AS ?patientAverage)
    WHERE { GRAPH ?g { ?quantity sphn:hasValue ?value } }
    GROUP BY ?g }
}"""
MASKED = PREFIX + """SELECT (SUM(IF(?value = 70, ?value, 0)) AS ?summary)
WHERE { GRAPH ?g { ?quantity sphn:hasValue ?value } }"""
COUNT = PREFIX + """SELECT (COUNT(DISTINCT ?g) AS ?patients)
WHERE { GRAPH ?g { ?quantity sphn:hasValue ?value } }"""
EXCLUDE = PREFIX + """SELECT (COUNT(DISTINCT ?g) AS ?patients)
WHERE { GRAPH ?g { ?quantity sphn:hasValue ?value . FILTER(?value != 70) } }"""


def fixture():
    """Nuovo scenario indipendente; non e un modello di sessione per produzione."""
    dataset, mapping = Dataset(), {}
    for index, values in enumerate(((10, 20), (30,), (40,), (50,), (60,), (70,)), start=1):
        graph = URIRef(f"http://example.org/graph/diagram-{index}")
        mapping[str(graph)] = f"synthetic-person-{index}"
        for position, value in enumerate(values):
            quantity = URIRef(f"urn:diagram:quantity:{index}:{position}")
            dataset.graph(graph).add((quantity, SPHN.hasValue, Literal(value)))
    context = ExecutionContext("diagram-presenter", "independent-synthetic-demo",
        allowed_graphs=frozenset(mapping), graph_patients=mapping, history=ReleaseHistory())
    return dataset, context


def scalar(payload, column):
    return Decimal(payload["results"]["bindings"][0][column]["value"])


def expect_blocked(dataset, query, context, fragment):
    try:
        execute_checked(dataset, query, policy=HARDENED, context=context)
    except ResultBlocked as error:
        if fragment not in str(error):
            raise AssertionError(f"Blocco inatteso: {error}") from error
        return str(error)
    raise AssertionError("L'esempio avrebbe dovuto essere bloccato")


def run():
    dataset, context = fixture()
    mean = scalar(execute_checked(dataset, MEAN, policy=HARDENED, context=context), "cohortAverage")
    assert mean == Decimal(265) / Decimal(6)

    # Nuovo scenario: il blocco deve dipendere dalla coorte effettiva,
    # non da una query precedente sullo stesso dataset.
    dataset, context = fixture()
    exposed = scalar(execute_checked(dataset, MASKED), "summary")
    assert exposed == 70
    masked_reason = expect_blocked(dataset, MASKED, context, "Coorte insufficiente")

    # Verifica separata: ogni conteggio e ammesso dal profilo storico.
    dataset, _ = fixture()
    first = scalar(execute_checked(dataset, COUNT), "patients")
    second = scalar(execute_checked(dataset, EXCLUDE), "patients")
    assert (first, second) == (6, 5)

    # Scenario con memoria: lo stesso contesto e riusato tra le due richieste.
    dataset, context = fixture()
    assert scalar(execute_checked(dataset, COUNT, policy=HARDENED, context=context), "patients") == 6
    history_reason = expect_blocked(dataset, EXCLUDE, context, "Storico")
    return {
        "media_delle_medie": str(mean),
        "media_delle_sette_misure": "40",
        "somma_mascherata_default": str(exposed),
        "somma_mascherata_hardened": masked_reason,
        "conteggi_senza_controllo_storico": [int(first), int(second)],
        "secondo_conteggio_con_stesso_storico": history_reason,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
