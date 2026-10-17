"""Offline comparison of query execution results; never executes a query."""
from collections import Counter
from dataclasses import dataclass
import json
from typing import Literal, Mapping


class UnsupportedComparison(ValueError):
    pass


def _validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a SPARQL Results JSON object")
    if "boolean" in payload:
        if type(payload["boolean"]) is not bool or "results" in payload:
            raise ValueError("Invalid ASK result")
        return "ask"
    columns = payload.get("head", {}).get("vars")
    bindings = payload.get("results", {}).get("bindings")
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        raise ValueError("Invalid result columns")
    if len(columns) != len(set(columns)) or not isinstance(bindings, list):
        raise ValueError("Invalid SELECT result")
    for row in bindings:
        if not isinstance(row, dict) or not set(row) <= set(columns):
            raise ValueError("Invalid result binding")
        for cell in row.values():
            if not isinstance(cell, dict) or not isinstance(cell.get("value"), str):
                raise ValueError("Invalid RDF term")
            if cell.get("type") == "bnode":
                raise UnsupportedComparison("Blank-node results require an isomorphism comparator")
            if cell.get("type") not in {"uri", "literal"}:
                raise ValueError("Invalid RDF term type")
            if not set(cell) <= {"type", "value", "datatype", "xml:lang"}:
                raise ValueError("Unexpected RDF term metadata")
            if cell.get("type") == "uri" and ("datatype" in cell or "xml:lang" in cell):
                raise ValueError("Invalid URI metadata")
            if "datatype" in cell and "xml:lang" in cell:
                raise ValueError("Conflicting literal metadata")
            if any(not isinstance(cell[k], str) for k in ("datatype", "xml:lang") if k in cell):
                raise ValueError("Invalid literal metadata")
    return "select"


def equivalent(expected: dict, actual: dict, *, ordered: bool = False,
               column_mapping: Mapping[str, str] | None = None) -> bool:
    """Strict RDF-term equality with bag semantics unless ordered=True.

    column_mapping explicitly maps candidate column names to reference names;
    no guessing by column position or sorting cell values.
    """
    expected_kind, actual_kind = _validate(expected), _validate(actual)
    if expected_kind != actual_kind:
        return False
    if expected_kind == "ask":
        return expected["boolean"] == actual["boolean"]
    columns = expected["head"]["vars"]
    actual_columns = actual["head"]["vars"]
    mapping = dict(column_mapping or {})
    if not set(mapping) <= set(actual_columns):
        raise ValueError("Column mapping contains unknown candidate columns")
    mapped = [mapping.get(c, c) for c in actual_columns]
    if len(mapped) != len(set(mapped)):
        raise ValueError("Column mapping is not one-to-one")
    if set(columns) != set(mapped):
        return False

    def rows(payload, aliases):
        normalized = []
        for row in payload["results"]["bindings"]:
            translated = {aliases.get(k, k): v for k, v in row.items()}
            normalized.append(tuple(json.dumps(translated.get(c), sort_keys=True) for c in sorted(columns)))
        return normalized
    left, right = rows(expected, {}), rows(actual, mapping)
    return left == right if ordered else Counter(left) == Counter(right)


@dataclass(frozen=True)
class SemanticVerdict:
    status: Literal["match", "different", "not_evaluated", "unsupported", "error"]
    reason: str


class SemanticEvaluator:
    """Compare candidate and oracle results on the SAME dataset snapshot.

    Does not infer intent from a prompt, execute untrusted queries, or prove
    universal equivalence. Call only with results produced by trusted runners.
    """
    def run(self, expected: dict | None, actual: dict | None, *, ordered=False,
            column_mapping: Mapping[str, str] | None = None) -> SemanticVerdict:
        if expected is None or actual is None:
            return SemanticVerdict("not_evaluated", "Oracle or released candidate result unavailable")
        try:
            matches = equivalent(expected, actual, ordered=ordered, column_mapping=column_mapping)
        except UnsupportedComparison as error:
            return SemanticVerdict("unsupported", str(error))
        except (ValueError, TypeError, KeyError, AttributeError):
            return SemanticVerdict("error", "Invalid result payload or column mapping")
        return SemanticVerdict("match" if matches else "different", "Execution results compared on the supplied snapshot")
