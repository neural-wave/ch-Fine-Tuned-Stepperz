"""Controllo locale delle statistiche numeriche prima della restituzione."""

import json
import re
from decimal import Decimal, InvalidOperation

from rdflib import URIRef, Variable, Literal
from rdflib.plugins.sparql.aggregates import Aggregator
from rdflib.plugins.sparql.evalutils import _eval
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import Query, QueryContext, FrozenBindings, SPARQLError

from .compliance import PATIENT_PREFIX, SUPPORTED_AGGREGATES, numeric_variables, validate
from .parser import analyze
from .expressions import NUMERIC_TYPES, numeric_expression


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


def number(cell, *, count=False):
    try:
        if (not isinstance(cell, dict) or set(cell) != {"type", "datatype", "value"} or
                cell["type"] != "literal" or cell["datatype"] not in NUMERIC_TYPES or
                not isinstance(cell["value"], str) or len(cell["value"]) > 128):
            raise ResultBlocked("Valore incompatibile con una statistica numerica approvata.")
        if count and (cell["datatype"] != "http://www.w3.org/2001/XMLSchema#integer" or
                      not re.fullmatch(r"[0-9]{1,20}", cell["value"])):
            raise ResultBlocked("Valore incompatibile con un conteggio intero approvato.")
        datatype = cell["datatype"].rsplit("#", 1)[-1]
        if datatype not in {"decimal", "float", "double"} and not re.fullmatch(r"[+-]?[0-9]+", cell["value"]):
            raise ResultBlocked("Formato incompatibile con il datatype intero.")
        if datatype == "decimal" and not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", cell["value"]):
            raise ResultBlocked("Formato incompatibile con il datatype decimale.")
        value = Decimal(cell["value"])
        if not value.is_finite() or abs(value.adjusted()) > 1000:
            raise ResultBlocked("Statistica non finita o fuori dai limiti numerici.")
        return value
    except (InvalidOperation, ValueError, TypeError) as error:
        if isinstance(error, ResultBlocked):
            raise
        raise ResultBlocked("Valore numerico non valido.") from error


def check_payload(payload, columns, *, numeric_columns=()):
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
        for column, cell in rows[0].items():
            number(cell, count=column not in numeric_columns)
    except (KeyError, TypeError, AttributeError) as error:
        raise ResultBlocked("Risposta malformata.") from error


def execute_checked(dataset, query, *, min_patients=5, max_support_rows=100_000):
    """Esegue su un Dataset locale stabile; restituisce solo JSON verificato.

    COUNT/SUM/AVG globali, aritmetica numerica e un'unica variabile grafo.
    Non adatto a dataset modificati concorrentemente durante i controlli.
    """
    if type(min_patients) is not int or min_patients < 2:
        raise ValueError("min_patients deve essere un intero >= 2")
    if type(max_support_rows) is not int or max_support_rows < 1:
        raise ValueError("max_support_rows deve essere positivo")
    if not validate(query)["is_compliant"]:
        raise ResultBlocked("Query bloccata dal controllo statico.")
    _, tree, prepared = analyze(query)
    algebra = prepared.algebra
    all_nodes = list(nodes(algebra))
    groups = [n for n in all_nodes if n.name == "Group"]
    graphs = [n["term"] for n in all_nodes if n.name == "Graph"]
    if (len(groups) != 1 or groups[0]["expr"] or not graphs or
            any(not isinstance(g, Variable) for g in graphs) or len(set(graphs)) != 1):
        raise ResultBlocked("Struttura non supportata dal controllo della coorte.")
    graph_var = graphs[0]
    aggregates = [n for n in all_nodes if n.name.startswith("Aggregate_")]
    if not aggregates or any(n.name not in SUPPORTED_AGGREGATES for n in aggregates):
        raise ResultBlocked("Aggregazione non supportata dalla policy runtime.")
    measure_vars = {Variable(v[1:]) for v in numeric_variables(tree)}
    def refs(value):
        if isinstance(value, Variable):
            return {value}
        if isinstance(value, dict):
            return set().union(*(refs(v) for k, v in value.items() if k != "_vars"))
        if isinstance(value, (list, tuple)):
            return set().union(*(refs(v) for v in value))
        return set()
    origins = {}
    for aggregate_index, aggregate in enumerate(aggregates):
        argument = aggregate["vars"]
        if argument != "*" and not isinstance(argument, Variable) and not numeric_expression(argument, measure_vars):
            raise ResultBlocked("Argomento aggregato non supportato dal controllo della coorte.")
        if aggregate.name != "Aggregate_Count" and not numeric_expression(argument, measure_vars):
            raise ResultBlocked("SUM/AVG richiedono misure numeriche autorizzate.")
        if argument == "*" and aggregate["distinct"]:
            raise ResultBlocked("COUNT(DISTINCT *) non supportato dalla policy runtime.")
        origins[aggregate["res"]] = aggregate_index
    # Segue esclusivamente alias diretti di un aggregato verificato.
    for _ in range(len(all_nodes)):
        for node in all_nodes:
            if node.name == "Extend" and isinstance(node["expr"], Variable):
                if node["expr"] in origins:
                    origins[node["var"]] = origins[node["expr"]]
    projected = algebra["PV"]
    dependencies = {a["res"]: {i} for i, a in enumerate(aggregates)}
    definitions = {}
    for _ in range(len(all_nodes)):
        for node in all_nodes:
            if node.name == "Extend" and numeric_expression(node["expr"], set(dependencies)):
                used = refs(node["expr"])
                if used:
                    dependencies[node["var"]] = set().union(*(dependencies[v] for v in used))
                    definitions[node["var"]] = node["expr"]
    if not projected or any(v not in dependencies for v in projected):
        raise ResultBlocked("Proiezione non supportata dalla policy runtime numerica.")

    # Valuta lo stesso pattern WHERE prima dell'aggregazione. Le righe restano interne.
    support_vars = sorted({graph_var}.union(*(refs(a["vars"]) for a in aggregates)), key=str)
    support_algebra = CompValue("SelectQuery", p=CompValue("Project", p=groups[0]["p"], PV=support_vars),
                                PV=support_vars, datasetClause=None)
    support_query = Query(prepared.prologue, support_algebra)
    cohorts = [set() for _ in aggregates]
    accumulators = [Aggregator([a]) for a in aggregates]
    context = QueryContext(dataset, initBindings={})
    context.prologue = prepared.prologue
    for index, row in enumerate(dataset.query(support_query, use_store_provided=False)):
        if index >= max_support_rows:
            raise ResultBlocked("Limite di verifica della coorte superato.")
        binding = row.asdict()
        graph = binding.get(str(graph_var))
        if not isinstance(graph, URIRef) or not str(graph).startswith(PATIENT_PREFIX):
            raise ResultBlocked("Grafo non appartenente al dataset pazienti autorizzato.")
        frozen = FrozenBindings(context, {Variable(k): v for k, v in binding.items()})
        for index_aggregate, aggregate in enumerate(aggregates):
            argument = aggregate["vars"]
            if argument == "*":
                cohorts[index_aggregate].add(graph)
                accumulators[index_aggregate].update(frozen)
                continue
            try:
                value = _eval(argument, frozen)
            except SPARQLError:
                continue  # Valore non legato: non contribuisce all'aggregato.
            if isinstance(value, SPARQLError):
                raise ResultBlocked("Errore nella valutazione di una misura.")
            if aggregate.name != "Aggregate_Count":
                if not isinstance(value, Literal):
                    raise ResultBlocked("Una misura non e un letterale numerico.")
                number({"type": "literal", "datatype": str(value.datatype), "value": str(value)})
            cohorts[index_aggregate].add(graph)
            accumulators[index_aggregate].update(frozen)
    # Anche HAVING/ORDER BY possono dipendere da un aggregato non proiettato.
    used_aggregates = range(len(aggregates))
    if any(len(cohorts[i]) < min_patients for i in used_aggregates):
        raise ResultBlocked("Coorte insufficiente: risultato soppresso.")

    expected = {}
    for accumulator in accumulators:
        expected.update(accumulator.get_bindings())
    for _ in range(len(definitions)):
        for variable, expression in definitions.items():
            if refs(expression) <= set(expected):
                try:
                    value = _eval(expression, FrozenBindings(context, expected))
                except (SPARQLError, ArithmeticError) as error:
                    raise ResultBlocked("Errore in un'espressione statistica approvata.") from error
                if isinstance(value, SPARQLError) or not isinstance(value, Literal):
                    raise ResultBlocked("Espressione statistica priva di valore numerico.")
                expected[variable] = value

    payload = json.loads(dataset.query(prepared, use_store_provided=False).serialize(format="json"))
    count_columns = {str(v) for v in projected if v in origins and aggregates[origins[v]].name == "Aggregate_Count"}
    check_payload(payload, [str(v) for v in projected], numeric_columns={str(v) for v in projected} - count_columns)
    for column in projected:
        computed = expected[column]
        trusted = number({"type": "literal", "datatype": str(computed.datatype), "value": str(computed)})
        if number(payload["results"]["bindings"][0][str(column)]) != trusted:
            raise ResultBlocked("Risultato restituito incoerente con il pattern approvato.")
    return payload
