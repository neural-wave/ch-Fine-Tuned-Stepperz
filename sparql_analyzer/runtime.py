"""Controllo locale dei risultati COUNT, prima della loro restituzione."""

import json
import re

from rdflib import URIRef, Variable
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import Query

from .compliance import PATIENT_PREFIX, validate
from .parser import analyze


class ResultBlocked(ValueError):
    """Errore pubblico privo dei dati contenuti nel risultato bloccato."""


def nodes(value):
    if isinstance(value, dict):
        if isinstance(value, CompValue):
            yield value
        for key, child in value.items():
            if key != "_vars":
                yield from nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from nodes(child)


def check_payload(payload, columns):
    """Valida uno SPARQL Results JSON rispetto alle colonne COUNT approvate.

    Non autorizza da solo la risposta: non verifica provenienza o coorte.
    """
    try:
        if set(payload) != {"head", "results"}:
            raise ResultBlocked("Struttura della risposta inattesa.")
        if set(payload["head"]) != {"vars"} or payload["head"]["vars"] != columns:
            raise ResultBlocked("Colonne della risposta diverse da quelle approvate.")
        if set(payload["results"]) != {"bindings"}:
            raise ResultBlocked("Struttura dei risultati inattesa.")
        rows = payload["results"]["bindings"]
        if not isinstance(rows, list) or len(rows) != 1:
            raise ResultBlocked("Attesa una sola riga di conteggi globali.")
        if set(rows[0]) != set(columns):
            raise ResultBlocked("Colonne mancanti o aggiuntive nella riga.")
        for cell in rows[0].values():
            if (set(cell) != {"type", "datatype", "value"} or
                    cell["type"] != "literal" or
                    cell["datatype"] != "http://www.w3.org/2001/XMLSchema#integer" or
                    not isinstance(cell["value"], str) or
                    not re.fullmatch(r"[0-9]{1,20}", cell["value"])):
                raise ResultBlocked("Valore incompatibile con un conteggio intero approvato.")
    except (KeyError, TypeError, AttributeError) as error:
        raise ResultBlocked("Risposta malformata.") from error


def execute_checked(dataset, query, *, min_patients=5, max_support_rows=100_000):
    """Esegue su un Dataset locale stabile; restituisce solo JSON verificato.

    Policy runtime iniziale: COUNT globali diretti, un'unica variabile grafo.
    Non adatto a dataset modificati concorrentemente durante i controlli.
    """
    if type(min_patients) is not int or min_patients < 2:
        raise ValueError("min_patients deve essere un intero >= 2")
    if type(max_support_rows) is not int or max_support_rows < 1:
        raise ValueError("max_support_rows deve essere positivo")
    if not validate(query)["is_compliant"]:
        raise ResultBlocked("Query bloccata dal controllo statico.")
    _, _, prepared = analyze(query)
    algebra = prepared.algebra
    all_nodes = list(nodes(algebra))
    groups = [n for n in all_nodes if n.name == "Group"]
    graphs = [n["term"] for n in all_nodes if n.name == "Graph"]
    if (len(groups) != 1 or groups[0]["expr"] or not graphs or
            any(not isinstance(g, Variable) for g in graphs) or len(set(graphs)) != 1):
        raise ResultBlocked("Struttura non supportata dal controllo della coorte.")
    graph_var = graphs[0]
    aggregates = [n for n in all_nodes if n.name.startswith("Aggregate_")]
    if not aggregates or any(n.name != "Aggregate_Count" for n in aggregates):
        raise ResultBlocked("Sono supportati solo COUNT globali diretti.")
    origins = {}
    for number, aggregate in enumerate(aggregates):
        argument = aggregate["vars"]
        if argument != "*" and not isinstance(argument, Variable):
            raise ResultBlocked("Argomento COUNT non supportato dal controllo della coorte.")
        if argument == "*" and aggregate["distinct"]:
            raise ResultBlocked("COUNT(DISTINCT *) non supportato dalla policy runtime.")
        origins[aggregate["res"]] = number
    # Segue esclusivamente alias diretti di un aggregato verificato.
    for _ in range(len(all_nodes)):
        for node in all_nodes:
            if node.name == "Extend" and isinstance(node["expr"], Variable):
                if node["expr"] in origins:
                    origins[node["var"]] = origins[node["expr"]]
    projected = algebra["PV"]
    if not projected or any(v not in origins for v in projected):
        raise ResultBlocked("Proiezione non supportata dalla policy runtime COUNT.")

    # Valuta lo stesso pattern WHERE prima dell'aggregazione. Le righe restano interne.
    support_vars = list(dict.fromkeys([graph_var] + [a["vars"] for a in aggregates if isinstance(a["vars"], Variable)]))
    support_algebra = CompValue("SelectQuery", p=CompValue("Project", p=groups[0]["p"], PV=support_vars),
                                PV=support_vars, datasetClause=None)
    support_query = Query(prepared.prologue, support_algebra)
    cohorts = {str(v): set() for v in projected}
    counts = [0 for _ in aggregates]
    distinct_values = [set() for _ in aggregates]
    for index, row in enumerate(dataset.query(support_query, use_store_provided=False)):
        if index >= max_support_rows:
            raise ResultBlocked("Limite di verifica della coorte superato.")
        binding = row.asdict()
        graph = binding.get(str(graph_var))
        if not isinstance(graph, URIRef) or not str(graph).startswith(PATIENT_PREFIX):
            raise ResultBlocked("Grafo non appartenente al dataset pazienti autorizzato.")
        for number, aggregate in enumerate(aggregates):
            argument = aggregate["vars"]
            if argument == "*" or str(argument) in binding:
                value = tuple(row) if argument == "*" else binding[str(argument)]
                if not aggregate["distinct"] or value not in distinct_values[number]:
                    counts[number] += 1
                distinct_values[number].add(value)
        for column in projected:
            argument = aggregates[origins[column]]["vars"]
            if argument == "*" or str(argument) in binding:
                cohorts[str(column)].add(graph)
    if any(len(cohort) < min_patients for cohort in cohorts.values()):
        raise ResultBlocked("Coorte insufficiente: risultato soppresso.")

    payload = json.loads(dataset.query(prepared, use_store_provided=False).serialize(format="json"))
    check_payload(payload, [str(v) for v in projected])
    for column in projected:
        if int(payload["results"]["bindings"][0][str(column)]["value"]) != counts[origins[column]]:
            raise ResultBlocked("Conteggio restituito incoerente con il pattern approvato.")
    return payload
