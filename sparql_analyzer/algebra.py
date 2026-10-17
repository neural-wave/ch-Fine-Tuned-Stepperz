"""Visite condivise dell'algebra RDFLib, senza applicare policy."""

from rdflib import Variable
from rdflib.plugins.sparql.parserutils import CompValue


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


def refs(value):
    if isinstance(value, Variable):
        return {value}
    if isinstance(value, dict):
        return set().union(set(), *(refs(v) for k, v in value.items() if k != "_vars"))
    if isinstance(value, (list, tuple)):
        return set().union(set(), *(refs(v) for v in value))
    return set()


def count_variables(algebra):
    """Risultati COUNT e soli alias diretti; l'aritmetica cambia il contratto."""
    all_nodes = list(nodes(algebra))
    result = {node["res"] for node in all_nodes if node.name == "Aggregate_Count"}
    while True:
        before = set(result)
        for node in all_nodes:
            if node.name == "Extend" and isinstance(node["expr"], Variable) and node["expr"] in result:
                result.add(node["var"])
        if before == result:
            return result
