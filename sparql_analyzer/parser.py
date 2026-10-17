"""Parsing SPARQL e conversione degli alberi RDFLib in JSON."""

from pyparsing import ParseResults
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.term import Identifier, Variable


def isolate_subquery_scopes(algebra):
    """Alpha-renaming: solo le variabili proiettate attraversano uno scope.

    Modifica anche _vars, preservando i CompValue e le funzioni di valutazione
    RDFLib. I nomi generati non possono collidere con variabili dell'utente.
    """
    def refs(value):
        if isinstance(value, Variable):
            return {value}
        if isinstance(value, dict):
            return set().union(set(), *(refs(v) for v in value.values()))
        if isinstance(value, (list, tuple, set, frozenset)):
            return set().union(set(), *(refs(v) for v in value))
        return set()

    used = refs(algebra)
    counter = 0

    def fresh():
        nonlocal counter
        while True:
            counter += 1
            variable = Variable(f"__scope_{counter}")
            if variable not in used:
                used.add(variable)
                return variable

    def rewrite(value, mapping):
        if isinstance(value, Variable):
            return mapping.get(value, value)
        if isinstance(value, dict):
            if isinstance(value, CompValue) and value.name == "ToMultiSet":
                child = value.get("p")
                if isinstance(child, CompValue) and child.name != "values":
                    projection = child
                    while "PV" not in projection:
                        projection = projection["p"]
                    exported = set(projection["PV"])
                    local = {v: mapping.get(v, v) if v in exported else fresh()
                             for v in sorted(refs(child), key=str)}
                    value["p"] = rewrite(child, local)
                    if "_vars" in value:
                        value["_vars"] = rewrite(value["_vars"], mapping)
                    return value
            for key in list(value):
                value[key] = rewrite(value[key], mapping)
            return value
        if isinstance(value, list):
            return [rewrite(v, mapping) for v in value]
        if isinstance(value, tuple):
            return tuple(rewrite(v, mapping) for v in value)
        if isinstance(value, (set, frozenset)):
            return type(value)(rewrite(v, mapping) for v in value)
        return value

    return rewrite(algebra, {})


def to_tree(value):
    """Converte i nodi RDFLib in un albero JSON, senza perdere i tipi RDF."""
    if isinstance(value, Identifier):
        return {"type": type(value).__name__, "value": value.n3()}
    if isinstance(value, CompValue):
        return {"node": value.name, **{k: to_tree(v) for k, v in value.items()}}
    if isinstance(value, dict):
        return {str(k): to_tree(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, ParseResults)):
        return [to_tree(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [to_tree(v) for v in sorted(value, key=str)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Tipo di nodo non supportato: {type(value).__name__}")


def analyze(query):
    parsed = parseQuery(query)
    # La traduzione modifica il parse tree: salvarlo prima di tradurlo.
    syntax_tree = to_tree(parsed)
    prepared = translateQuery(parsed)
    isolate_subquery_scopes(prepared.algebra)
    return syntax_tree, to_tree(prepared.algebra), prepared


