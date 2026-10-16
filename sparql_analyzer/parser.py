"""Parsing SPARQL e conversione degli alberi RDFLib in JSON."""

from pyparsing import ParseResults
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.term import Identifier


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
    return syntax_tree, to_tree(prepared.algebra), prepared


