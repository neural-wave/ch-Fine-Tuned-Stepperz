"""Espressioni numeriche deterministiche ammesse dalla policy."""

from rdflib import Literal, Variable, XSD
from rdflib.plugins.sparql.parserutils import CompValue

NUMERIC_TYPES = {str(XSD[name]) for name in (
    "integer", "decimal", "float", "double", "int", "long", "short", "byte",
    "nonNegativeInteger", "positiveInteger", "nonPositiveInteger", "negativeInteger",
    "unsignedInt", "unsignedLong", "unsignedShort", "unsignedByte",
)}
NUMERIC_NODES = {"AdditiveExpression", "MultiplicativeExpression", "UnaryMinus", "UnaryPlus",
                 "Builtin_ABS", "Builtin_ROUND", "Builtin_CEIL", "Builtin_FLOOR"}


def boolean_expression(value, allowed_variables):
    if isinstance(value, Literal):
        return value.datatype == XSD.boolean
    if not isinstance(value, CompValue):
        return False
    if value.name == "RelationalExpression":
        return all(numeric_expression(v, allowed_variables) for k, v in value.items()
                   if k not in {"_vars", "op"})
    if value.name in {"ConditionalAndExpression", "ConditionalOrExpression", "UnaryNot"}:
        def boolean_children(child):
            if isinstance(child, (list, tuple)):
                return all(boolean_children(v) for v in child)
            return boolean_expression(child, allowed_variables)
        return all(boolean_children(v) for k, v in value.items() if k not in {"_vars", "op"})
    return False


def numeric_expression(value, allowed_variables):
    """Non autorizza funzioni arbitrarie, stringhe o accessi al dataset."""
    if isinstance(value, Variable):
        return value in allowed_variables
    if isinstance(value, Literal):
        return str(value.datatype) in NUMERIC_TYPES
    if isinstance(value, CompValue):
        if value.name == "Builtin_IF":
            return (boolean_expression(value["arg1"], allowed_variables) and
                    numeric_expression(value["arg2"], allowed_variables) and
                    numeric_expression(value["arg3"], allowed_variables))
        if value.name == "Builtin_COALESCE":
            return numeric_expression(value["arg"], allowed_variables)
        if value.name not in NUMERIC_NODES:
            return False
        children = [v for k, v in value.items() if k not in {"_vars", "op"}]
        return bool(children) and all(numeric_expression(v, allowed_variables) for v in children)
    if isinstance(value, (list, tuple)):
        return all(numeric_expression(v, allowed_variables) for v in value)
    return False
