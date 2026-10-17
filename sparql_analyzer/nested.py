"""Valutazione locale di aggregazioni annidate con provenienza dei risultati.

I risultati intermedi restano privati. La soglia si applica alle dipendenze
dell'output, non ai singoli gruppi intermedi. Nessun hook globale di RDFLib.
"""

import json
from dataclasses import dataclass, field

from rdflib import Literal, URIRef, Variable
from rdflib.plugins.sparql.aggregates import Aggregator
from rdflib.plugins.sparql.evaluate import evalPart
from rdflib.plugins.sparql.evalutils import _eval
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import FrozenBindings, Query, QueryContext, SPARQLError

from .compliance import PATIENT_PREFIX
from .runtime import ResultBlocked, check_payload, number


def refs(value):
    if isinstance(value, Variable):
        return {value}
    if isinstance(value, dict):
        return set().union(set(), *(refs(v) for k, v in value.items() if k != "_vars"))
    if isinstance(value, (tuple, list)):
        return set().union(set(), *(refs(v) for v in value))
    return set()


@dataclass
class Row:
    binding: dict
    origins: dict = field(default_factory=dict)
    support: set = field(default_factory=set)
    controls: dict = field(default_factory=dict)
    counts: set = field(default_factory=set)


def merged(rows, binding):
    result = Row(dict(binding))
    for row in rows:
        result.support.update(row.support)
        result.counts.update(row.counts)
        for variable, source in row.origins.items():
            result.origins.setdefault(variable, set()).update(source)
        for control, source in row.controls.items():
            result.controls.setdefault(control, set()).update(source)
    return result


def sources(row, expression):
    return set().union(set(), *(row.origins.get(v, set()) for v in refs(expression)))


def execute_nested(dataset, prepared, *, min_patients, max_support_rows):
    context = QueryContext(dataset, initBindings={})
    context.prologue = prepared.prologue
    used = refs(prepared.algebra)
    serial = 0
    visited = 0

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
            if visited > max_support_rows:
                raise ResultBlocked("Limite di verifica della coorte superato.")
            result.append(row)
        return result

    def materialize(rows, handle):
        return CompValue("ToMultiSet", p=CompValue("values", res=[
            {**r.binding, handle: Literal(i)} for i, r in enumerate(rows)
        ]))

    def raw(node):
        columns = sorted(refs(node), key=str)
        algebra = CompValue("SelectQuery", p=CompValue("Project", p=node, PV=columns),
                            PV=columns, datasetClause=None)
        for result in dataset.query(Query(prepared.prologue, algebra), use_store_provided=False):
            binding = {Variable(k): v for k, v in result.asdict().items()}
            if node.name == "Graph":
                graph = binding.get(node["term"], node["term"])
                if not isinstance(graph, URIRef) or not str(graph).startswith(PATIENT_PREFIX):
                    raise ResultBlocked("Grafo non appartenente al dataset pazienti autorizzato.")
                yield Row(binding, {v: {graph} for v in binding}, {graph})
            else:
                # Un pattern nel default graph non prova l'origine paziente.
                yield Row(binding, controls={id(node): set()} if node["triples"] else {})

    def aggregate(node):
        group = node["p"]
        if any(a["vars"] == "*" and a["distinct"] for a in node["A"]):
            raise ResultBlocked("COUNT(DISTINCT *) non supportato dalla policy runtime.")
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
            for row in members:
                frozen = FrozenBindings(context, row.binding)
                for a in node["A"]:
                    argument = a["vars"]
                    if argument == "*":
                        origins[a["res"]].update(row.support)
                        continue
                    try:
                        value = _eval(argument, frozen)
                    except SPARQLError:
                        continue
                    if isinstance(value, SPARQLError):
                        continue
                    if a.name in {"Aggregate_Sum", "Aggregate_Avg"}:
                        if not isinstance(value, Literal):
                            raise ResultBlocked("Una misura non e un letterale numerico.")
                        number({"type": "literal", "datatype": str(value.datatype), "value": str(value)})
                    origins[a["res"]].update(sources(row, argument))
                accumulator.update(frozen)
            output = merged(members, accumulator.get_bindings())
            output.origins = origins
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
                    if name == "LeftJoin" and "expr" in node and refs(node["expr"]):
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
                        output.origins[variable] = sources(original, expression)
                        output.counts.discard(variable)
                        if isinstance(expression, Variable) and expression in original.counts:
                            output.counts.add(variable)
                    elif name in {"Filter", "OrderBy"} and refs(node["expr"]):
                        output.controls[id(node)] = sources(original, node["expr"])
                    yield output
            return budget(transformed())
        raise ResultBlocked("Operazione non supportata dal controllo di provenienza annidato.")

    rows = evaluate(prepared.algebra)
    columns = prepared.algebra["PV"]
    if len(rows) != 1 or set(rows[0].binding) != set(columns):
        raise ResultBlocked("Attesa una sola riga di statistiche globali.")
    row = rows[0]
    dependencies = [row.origins.get(v, set()) for v in columns] + list(row.controls.values())
    if any(len(cohort) < min_patients for cohort in dependencies):
        raise ResultBlocked("Coorte insufficiente: risultato soppresso.")
    payload = json.loads(dataset.query(prepared, use_store_provided=False).serialize(format="json"))
    check_payload(payload, [str(v) for v in columns],
                  numeric_columns={str(v) for v in columns if v not in row.counts})
    for variable in columns:
        value = row.binding[variable]
        if not isinstance(value, Literal):
            raise ResultBlocked("Output non numerico.")
        expected = number({"type": "literal", "datatype": str(value.datatype), "value": str(value)})
        if number(payload["results"]["bindings"][0][str(variable)]) != expected:
            raise ResultBlocked("Risultato restituito incoerente con il pattern approvato.")
    return payload
