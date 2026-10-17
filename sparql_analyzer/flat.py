"""Percorso di esecuzione per aggregazioni globali semplici."""
import json
from rdflib import URIRef, Variable, Literal
from rdflib.plugins.sparql.aggregates import Aggregator
from rdflib.plugins.sparql.evalutils import _eval
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import Query, QueryContext, FrozenBindings, SPARQLError
from .vocabulary import PATIENT_PREFIX, SUPPORTED_AGGREGATES
from .analysis import numeric_variables
from .algebra import refs
from .expressions import numeric_expression
from .results import ResultBlocked, check_payload, number, nodes


def execute_flat(dataset, tree, prepared, *, policy, min_patients, max_support_rows):
    algebra = prepared.algebra
    all_nodes = list(nodes(algebra))
    groups = [n for n in all_nodes if n.name == "Group"]
    graphs = [n["term"] for n in all_nodes if n.name == "Graph"]
    if (len(groups) != 1 or groups[0]["expr"] or not graphs or
            any(not isinstance(g, Variable) for g in graphs) or len(set(graphs)) != 1):
        raise ResultBlocked("Struttura non supportata dal controllo della coorte.")
    graph_var = graphs[0]
    aggregates = [n for n in all_nodes if n.name.startswith("Aggregate_")]
    if policy.enabled("runtime_aggregates") and (not aggregates or any(n.name not in SUPPORTED_AGGREGATES for n in aggregates)):
        raise ResultBlocked("Aggregazione non supportata dalla policy runtime.")
    measure_vars = {Variable(v[1:]) for v in numeric_variables(tree)} if policy.enabled("numeric_analysis") else set()
    origins = {}
    for aggregate_index, aggregate in enumerate(aggregates):
        argument = aggregate["vars"]
        if policy.enabled("runtime_expressions") and argument != "*" and not isinstance(argument, Variable) and not numeric_expression(argument, measure_vars):
            raise ResultBlocked("Argomento aggregato non supportato dal controllo della coorte.")
        if policy.enabled("runtime_expressions") and aggregate.name != "Aggregate_Count" and not numeric_expression(argument, measure_vars):
            raise ResultBlocked("SUM/AVG richiedono misure numeriche autorizzate.")
        if policy.enabled("runtime_distinct_star") and argument == "*" and aggregate["distinct"]:
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
    if policy.enabled("runtime_expressions") and (not projected or any(v not in dependencies for v in projected)):
        raise ResultBlocked("Proiezione non supportata dalla policy runtime numerica.")

    # Valuta lo stesso pattern WHERE prima dell'aggregazione. Le righe restano interne.
    support_vars = sorted({graph_var}.union(*(refs(a["vars"]) for a in aggregates)), key=str)
    support_algebra = CompValue("SelectQuery", p=CompValue("Project", p=groups[0]["p"], PV=support_vars),
                                PV=support_vars, datasetClause=None)
    support_query = Query(prepared.prologue, support_algebra)
    cohorts = [set() for _ in aggregates]
    accumulators = [Aggregator([a]) for a in aggregates] if policy.enabled("result_consistency") else None
    context = QueryContext(dataset, initBindings={})
    context.prologue = prepared.prologue
    for index, row in enumerate(dataset.query(support_query, use_store_provided=False)):
        if policy.enabled("runtime_work_limit") and index >= max_support_rows:
            raise ResultBlocked("Limite di verifica della coorte superato.")
        binding = row.asdict()
        graph = binding.get(str(graph_var))
        if policy.enabled("runtime_graph_scope") and (not isinstance(graph, URIRef) or not str(graph).startswith(PATIENT_PREFIX)):
            raise ResultBlocked("Grafo non appartenente al dataset pazienti autorizzato.")
        frozen = FrozenBindings(context, {Variable(k): v for k, v in binding.items()})
        for index_aggregate, aggregate in enumerate(aggregates):
            argument = aggregate["vars"]
            if argument == "*":
                cohorts[index_aggregate].add(graph)
                if accumulators is not None:
                    accumulators[index_aggregate].update(frozen)
                continue
            try:
                value = _eval(argument, frozen)
            except SPARQLError:
                continue  # Valore non legato: non contribuisce all'aggregato.
            if isinstance(value, SPARQLError):
                raise ResultBlocked("Errore nella valutazione di una misura.")
            if policy.enabled("runtime_measures") and aggregate.name != "Aggregate_Count":
                if not isinstance(value, Literal):
                    raise ResultBlocked("Una misura non e un letterale numerico.")
                number({"type": "literal", "datatype": str(value.datatype), "value": str(value)}, policy=policy)
            cohorts[index_aggregate].add(graph)
            if accumulators is not None:
                accumulators[index_aggregate].update(frozen)
    # Anche HAVING/ORDER BY possono dipendere da un aggregato non proiettato.
    output_aggregates = set().union(set(), *(dependencies.get(v, set()) for v in projected))
    used_aggregates = set(output_aggregates) if policy.enabled("runtime_cohort") else set()
    if policy.enabled("runtime_control_cohort"):
        used_aggregates.update(set(range(len(aggregates))) - output_aggregates)
    if any(len(cohorts[i]) < min_patients for i in used_aggregates):
        raise ResultBlocked("Coorte insufficiente: risultato soppresso.")

    if policy.enabled("result_consistency"):
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
    check_payload(payload, [str(v) for v in projected], numeric_columns={str(v) for v in projected} - count_columns, policy=policy)
    if policy.enabled("result_consistency"):
        for column in projected:
            computed = expected[column]
            trusted = number({"type": "literal", "datatype": str(computed.datatype), "value": str(computed)}, policy=policy)
            if number(payload["results"]["bindings"][0][str(column)], policy=policy) != trusted:
                raise ResultBlocked("Risultato restituito incoerente con il pattern approvato.")
    return payload
