"""Righe interne e provenienza: nessun rilascio di dati o policy globale."""

from dataclasses import dataclass, field
from .algebra import refs


@dataclass
class Row:
    binding: dict
    origins: dict = field(default_factory=dict)
    support: set = field(default_factory=set)
    controls: dict = field(default_factory=dict)
    counts: set = field(default_factory=set)
    dependencies: dict = field(default_factory=dict)


def merged(rows, binding):
    result = Row(dict(binding))
    for row in rows:
        result.support.update(row.support)
        result.counts.update(row.counts)
        for variable, source in row.origins.items():
            result.origins.setdefault(variable, set()).update(source)
        for control, source in row.controls.items():
            result.controls.setdefault(control, set()).update(source)
        for variable, dependencies in row.dependencies.items():
            target = result.dependencies.setdefault(variable, {})
            for aggregate, source in dependencies.items():
                target.setdefault(aggregate, set()).update(source)
    return result


def sources(row, expression):
    return set().union(set(), *(row.origins.get(v, set()) for v in refs(expression)))


def effective_sources(row, expression, context):
    """Segui solo il ramo valutato; zeri artificiali non aumentano la coorte.

    Una misura letta direttamente conserva la provenienza anche se vale zero.
    Gli zeri prodotti da trasformazioni vengono trattati conservativamente.
    """
    from rdflib import Literal, Variable
    from rdflib.plugins.sparql.evalutils import _eval, _ebv
    from rdflib.plugins.sparql.parserutils import CompValue
    from rdflib.plugins.sparql.sparql import FrozenBindings, SPARQLError
    if isinstance(expression, Variable):
        return set(row.origins.get(expression, set()))
    if isinstance(expression, Literal):
        return set()
    if isinstance(expression, (list, tuple)):
        return set().union(set(), *(effective_sources(row, e, context) for e in expression))
    if not isinstance(expression, CompValue):
        return set()
    frozen = FrozenBindings(context, row.binding)
    if expression.name == "Builtin_IF":
        selected = expression["arg2"] if _ebv(expression["arg1"], frozen) else expression["arg3"]
        origin = effective_sources(row, selected, context)
        value = _eval(selected, frozen)
        if origin or isinstance(value, SPARQLError) or value.toPython() == 0:
            return origin
        # Un indicatore costante non nullo dipende dalla condizione scelta.
        return sources(row, expression["arg1"])
    if expression.name == "Builtin_COALESCE":
        for argument in expression["arg"]:
            try:
                value = _eval(argument, frozen)
            except SPARQLError:
                continue
            if not isinstance(value, SPARQLError):
                return effective_sources(row, argument, context)
        return set()
    try:
        value = _eval(expression, frozen)
    except SPARQLError:
        return set()
    if isinstance(value, SPARQLError) or (isinstance(value, Literal) and value.toPython() == 0):
        return set()
    return set().union(set(), *(effective_sources(row, v, context) for key, v in expression.items() if key not in {"_vars", "op"}))


