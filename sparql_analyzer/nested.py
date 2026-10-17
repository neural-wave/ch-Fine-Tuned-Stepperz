"""Valutazione locale di aggregazioni annidate con provenienza dei risultati.

I risultati intermedi restano privati. La soglia si applica alle dipendenze
dell'output, non ai singoli gruppi intermedi. Nessun hook globale di RDFLib.
"""

import json

from rdflib import Literal, URIRef, Variable
from rdflib.plugins.sparql.aggregates import Aggregator
from rdflib.plugins.sparql.evaluate import evalPart
from rdflib.plugins.sparql.evalutils import _eval
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import FrozenBindings, Query, QueryContext, SPARQLError

from .vocabulary import PATIENT_PREFIX, SUPPORTED_AGGREGATES
from .results import ResultBlocked, UnsupportedExecution, check_payload, number
from .policy import DEFAULT_POLICY
from .algebra import refs, nodes
from .provenance import Row, merged, sources, effective_sources
from .analysis import numeric_variables
from .parser import to_tree
from .expressions import numeric_expression


def execute_nested(dataset, prepared, *, policy=DEFAULT_POLICY, min_patients, max_support_rows, tree=None,
                   execution_context=None, released_cohorts=None):
    context = QueryContext(dataset, initBindings={})
    context.prologue = prepared.prologue
    used = refs(prepared.algebra)
    serial = 0
    visited = 0
    numeric = {Variable(v[1:]) for v in numeric_variables(tree if tree is not None else to_tree(prepared.algebra))} if policy.enabled("runtime_expressions") else set()

    def lineage(row, expression):
        return effective_sources(row, expression, context) if policy.enabled("privacy_effective_contributors") else sources(row, expression)

    def fresh():
        nonlocal serial
        while True:
            serial += 1
            variable = Variable(f"__lineage_{serial}")
            if variable not in used:
                used.add(variable)
                return variable

    def budget(rows):
        nonlocal visited
        result = []
        for row in rows:
            visited += 1
            if policy.enabled("runtime_work_limit") and visited > max_support_rows:
                raise ResultBlocked("Limite di verifica della coorte superato.")
            result.append(row)
        return result

    def materialize(rows, handle):
        return CompValue("ToMultiSet", p=CompValue("values", res=[
            {**r.binding, handle: Literal(i)} for i, r in enumerate(rows)
        ]))

    def raw(node):
        if (node.name == "Graph" and policy.enabled("privacy_effective_contributors") and
                any(child.name == "AggregateJoin" for child in nodes(node["p"]))):
            raise ResultBlocked("Provenienza di aggregati interni a GRAPH non verificabile con la policy dei contributi effettivi.")
        columns = sorted(refs(node), key=str)
        algebra = CompValue("SelectQuery", p=CompValue("Project", p=node, PV=columns),
                            PV=columns, datasetClause=None)
        for result in dataset.query(Query(prepared.prologue, algebra), use_store_provided=False):
            binding = {Variable(k): v for k, v in result.asdict().items()}
            if node.name == "Graph":
                graph = binding.get(node["term"], node["term"])
                if policy.enabled("runtime_graph_scope") and (not isinstance(graph, URIRef) or not str(graph).startswith(PATIENT_PREFIX)):
                    raise ResultBlocked("Grafo non appartenente al dataset pazienti autorizzato.")
                person = graph
                if policy.enabled("privacy_distinct_persons"):
                    person = execution_context.graph_patients.get(str(graph))
                    if person is None:
                        raise ResultBlocked("Grafo privo di identita canonica nel mapping fidato.")
                annotated = Row(binding, {v: {person} for v in binding}, {person})
                if policy.enabled("privacy_effective_contributors"):
                    # GRAPH viene eseguito da RDFLib: ripristina la provenienza
                    # degli alias locali, senza considerare un BIND(0) una misura.
                    for child in reversed(list(nodes(node["p"]))):
                        if child.name == "Extend" and child["var"] in binding:
                            try:
                                computed = _eval(child["expr"], FrozenBindings(context, binding))
                                if computed == binding[child["var"]]:
                                    annotated.origins[child["var"]] = lineage(annotated, child["expr"])
                            except SPARQLError:
                                continue
                yield annotated
            else:
                # Un pattern nel default graph non prova l'origine paziente.
                yield Row(binding, controls={id(node): set()} if node["triples"] and policy.enabled("control_analysis") else {})

    def aggregate(node):
        group = node["p"]
        if policy.enabled("runtime_aggregates") and any(a.name not in SUPPORTED_AGGREGATES | {"Aggregate_Sample"} for a in node["A"]):
            raise ResultBlocked("Aggregazione non supportata dalla policy runtime.")
        if policy.enabled("runtime_distinct_star") and any(a["vars"] == "*" and a["distinct"] for a in node["A"]):
            raise ResultBlocked("COUNT(DISTINCT *) non supportato dalla policy runtime.")
        if policy.enabled("runtime_expressions"):
            for a in node["A"]:
                if a.name == "Aggregate_Sample":
                    continue  # Chiave di gruppo generata da RDFLib.
                argument = a["vars"]
                if argument != "*" and not isinstance(argument, Variable) and not numeric_expression(argument, numeric):
                    raise ResultBlocked("Argomento aggregato non supportato dal controllo della coorte.")
                if a.name in {"Aggregate_Sum", "Aggregate_Avg"} and not numeric_expression(argument, numeric):
                    raise ResultBlocked("SUM/AVG richiedono misure numeriche autorizzate.")
        rows = evaluate(group["p"])
        expressions = group["expr"]
        buckets = {} if expressions is not None else {(): []}
        for row in rows:
            frozen = FrozenBindings(context, row.binding)
            key = tuple(_eval(e, frozen, False) for e in expressions) if expressions else ()
            buckets.setdefault(key, []).append(row)
        result = []
        for members in buckets.values():
            accumulator = Aggregator(node["A"])
            origins = {a["res"]: set() for a in node["A"]}
            dependencies = {a["res"]: {} for a in node["A"]}
            for row in members:
                frozen = FrozenBindings(context, row.binding)
                for a in node["A"]:
                    argument = a["vars"]
                    if policy.enabled("privacy_effective_contributors"):
                        for variable in refs(argument):
                            for key, source in row.dependencies.get(variable, {}).items():
                                dependencies[a["res"]].setdefault(key, set()).update(source)
                    if argument == "*":
                        origins[a["res"]].update(row.support)
                        continue
                    try:
                        value = _eval(argument, frozen)
                    except SPARQLError:
                        continue
                    if isinstance(value, SPARQLError):
                        continue
                    if policy.enabled("runtime_measures") and a.name in {"Aggregate_Sum", "Aggregate_Avg"}:
                        if not isinstance(value, Literal):
                            raise ResultBlocked("Una misura non e un letterale numerico.")
                        number({"type": "literal", "datatype": str(value.datatype), "value": str(value)}, policy=policy)
                    origins[a["res"]].update(lineage(row, argument))
                accumulator.update(frozen)
            output = merged(members, accumulator.get_bindings())
            output.origins = origins
            if policy.enabled("privacy_effective_contributors"):
                for a in node["A"]:
                    dependencies[a["res"]][id(a)] = set(origins[a["res"]])
                output.dependencies = dependencies
            output.counts = {a["res"] for a in node["A"] if a.name == "Aggregate_Count"}
            result.append(output)
        return budget(result)

    def evaluate(node):
        name = node.name
        if name in {"SelectQuery", "ToMultiSet"}:
            return evaluate(node["p"])
        if name in {"Graph", "BGP"}:
            return budget(raw(node))
        if name == "AggregateJoin":
            return aggregate(node)
        if name == "Project":
            result = []
            for row in evaluate(node["p"]):
                projected = {v: row.binding[v] for v in node["PV"] if v in row.binding}
                output = merged([row], projected)
                output.origins = {v: row.origins.get(v, set()) for v in projected}
                output.dependencies = {v: row.dependencies[v] for v in projected if v in row.dependencies}
                output.counts.intersection_update(projected)
                result.append(output)
            return budget(result)
        if name == "Reduced":
            reduced = []
            for row in evaluate(node["p"]):
                if reduced and row.binding == reduced[-1].binding:
                    reduced[-1] = merged([reduced[-1], row], row.binding)
                else:
                    reduced.append(row)
            return budget(reduced)
        if name == "Distinct":
            unique = {}
            for row in evaluate(node["p"]):
                key = frozenset(row.binding.items())
                unique[key] = merged([unique[key], row], row.binding) if key in unique else row
            return budget(unique.values())
        if name in {"Join", "LeftJoin", "Union", "Minus"}:
            left, right = evaluate(node["p1"]), evaluate(node["p2"])
            h1, h2 = fresh(), fresh()
            operation = node.clone()
            operation["p1"], operation["p2"] = materialize(left, h1), materialize(right, h2)
            operation["lazy"] = False
            def joined():
                for binding in evalPart(context, operation):
                    plain = dict(binding)
                    members = []
                    for handle, rows in ((h1, left), (h2, right)):
                        if handle in plain:
                            members.append(rows[int(plain.pop(handle))])
                    output = merged(members, plain)
                    if policy.enabled("control_analysis") and name == "LeftJoin" and "expr" in node and refs(node["expr"]):
                        output.controls[id(node)] = sources(output, node["expr"])
                    yield output
            return budget(joined())
        if name in {"Extend", "Filter", "OrderBy", "Slice"}:
            rows = evaluate(node["p"])
            handle = fresh()
            operation = node.clone()
            operation["p"] = materialize(rows, handle)
            operation["_vars"] = set(node.get("_vars") or ()) | {handle}
            def transformed():
                for binding in evalPart(context, operation):
                    plain = dict(binding)
                    original = rows[int(plain.pop(handle))]
                    output = merged([original], plain)
                    if name == "Extend":
                        variable, expression = node["var"], node["expr"]
                        output.origins[variable] = lineage(original, expression)
                        if policy.enabled("privacy_effective_contributors"):
                            inherited = {}
                            for dependency in refs(expression):
                                for key, source in original.dependencies.get(dependency, {}).items():
                                    inherited.setdefault(key, set()).update(source)
                            output.dependencies[variable] = inherited
                        output.counts.discard(variable)
                        if isinstance(expression, Variable) and expression in original.counts:
                            output.counts.add(variable)
                    elif policy.enabled("control_analysis") and name in {"Filter", "OrderBy"} and refs(node["expr"]):
                        output.controls[id(node)] = sources(original, node["expr"])
                    yield output
            return budget(transformed())
        raise UnsupportedExecution("Operazione non supportata dal controllo di provenienza annidato; disabilitare support_analysis per usare il motore originale.")

    rows = evaluate(prepared.algebra)
    columns = prepared.algebra["PV"]
    if policy.enabled("runtime_expressions") and not set(columns) <= numeric:
        raise ResultBlocked("Proiezione non supportata dalla policy runtime numerica.")
    if policy.enabled("runtime_global_group") and (len(rows) != 1 or set(rows[0].binding) != set(columns)):
        raise ResultBlocked("Attesa una sola riga di statistiche globali.")
    for row in rows:
        dependencies = [row.origins.get(v, set()) for v in columns] if policy.enabled("runtime_cohort") else []
        if policy.enabled("privacy_effective_contributors"):
            dependencies += [source for v in columns for source in row.dependencies.get(v, {}).values()]
        if policy.enabled("runtime_control_cohort"):
            dependencies += list(row.controls.values())
        if any(len(cohort) < min_patients for cohort in dependencies):
            raise ResultBlocked("Coorte insufficiente: risultato soppresso.")
    payload = json.loads(dataset.query(prepared, use_store_provided=False).serialize(format="json"))
    count_columns = set.intersection(*(row.counts for row in rows)) if rows else set()
    check_payload(payload, [str(v) for v in columns], policy=policy,
                  numeric_columns={str(v) for v in columns if v not in count_columns})
    if policy.enabled("result_consistency"):
        from collections import Counter
        expected, actual = [], []
        for row in rows:
            values = []
            for variable in columns:
                value = row.binding[variable]
                if not isinstance(value, Literal):
                    raise ResultBlocked("Output non numerico.")
                values.append(number({"type": "literal", "datatype": str(value.datatype), "value": str(value)}, policy=policy))
            expected.append(tuple(values))
        for binding in payload["results"]["bindings"]:
            actual.append(tuple(number(binding[str(v)], policy=policy) for v in columns))
        if Counter(actual) != Counter(expected):
            raise ResultBlocked("Risultato restituito incoerente con il pattern approvato.")
    if released_cohorts is not None:
        for row in rows:
            released_cohorts.extend(frozenset(row.origins.get(v, set())) for v in columns)
            if policy.enabled("privacy_effective_contributors"):
                released_cohorts.extend(frozenset(c) for v in columns for c in row.dependencies.get(v, {}).values())
            released_cohorts.extend(frozenset(c) for c in row.controls.values())
    return payload
