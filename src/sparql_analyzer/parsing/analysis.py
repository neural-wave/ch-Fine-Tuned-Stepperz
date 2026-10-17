"""Analisi pure delle variabili e dell’algebra serializzata."""

from rdflib.util import from_n3
from sparql_analyzer.shared.vocabulary import NUMERIC_PREDICATES
from sparql_analyzer.shared.expressions import NUMERIC_NODES, NUMERIC_TYPES
from sparql_analyzer.configuration.policy import DEFAULT_POLICY

def numeric_variables(tree):
    """Variabili di misura dirette o derivate con sola aritmetica verificata.

    La classificazione dipende dalla correttezza del vocabolario del dataset.
    Non basta il datatype numerico: hasIdentifier non e una misura.
    """
    nodes = list(walk(tree))
    result = set()
    unsafe = set()
    for node in nodes:
        if node.get("node") == "Graph":
            unsafe |= variables(node.get("term"))
        if node.get("node") != "BGP":
            continue
        for subject, predicate, obj in node.get("triples", []):
            unsafe |= variables(subject)
            if uri(predicate) in NUMERIC_PREDICATES:
                result |= variables(obj)
            else:
                unsafe |= variables(obj)
    result -= unsafe

    def boolean(value):
        if isinstance(value, dict):
            name = value.get("node")
            if name == "RelationalExpression":
                return all(numeric(v) for k, v in value.items() if k not in {"node", "_vars", "op"})
            if name in {"ConditionalAndExpression", "ConditionalOrExpression", "UnaryNot"}:
                return all(boolean(v) for k, v in value.items() if k not in {"node", "_vars", "op"})
            if value.get("type") == "Literal":
                return str(getattr(from_n3(value["value"]), "datatype", None)) == "http://www.w3.org/2001/XMLSchema#boolean"
        if isinstance(value, list):
            return all(boolean(v) for v in value)
        return False

    def numeric(value):
        if isinstance(value, dict):
            if value.get("type") == "Variable":
                return value["value"] in result
            if value.get("type") == "Literal":
                # Il datatype viene verificato sul valore RDF a runtime.
                literal = from_n3(value["value"])
                return str(getattr(literal, "datatype", None)) in NUMERIC_TYPES
            if value.get("node") == "Builtin_IF":
                return boolean(value.get("arg1")) and numeric(value.get("arg2")) and numeric(value.get("arg3"))
            if value.get("node") == "Builtin_COALESCE":
                return numeric(value.get("arg"))
            if value.get("node") not in NUMERIC_NODES:
                return False
            return all(numeric(v) for k, v in value.items() if k not in {"node", "_vars", "op"})
        if isinstance(value, list):
            return all(numeric(v) for v in value)
        return False

    for _ in range(len(nodes)):
        for node in nodes:
            name = node.get("node")
            if name == "Aggregate_Count" or (
                name in {"Aggregate_Sum", "Aggregate_Avg", "Aggregate_Sample", "Aggregate_Min", "Aggregate_Max"}
                and numeric(node.get("vars"))
            ):
                result |= variables(node.get("res")) - unsafe
            if node.get("node") == "Extend" and numeric(node.get("expr")):
                result |= variables(node.get("var")) - unsafe
    return result


def walk(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key != "_vars":
                yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def variables(value):
    return {v["value"] for v in walk(value) if v.get("type") == "Variable"}


def uri(value):
    if isinstance(value, dict) and value.get("type") == "URIRef":
        return value["value"][1:-1]
    return None


class QueryAnalysis:
    """Fatti condivisi dalle regole; ogni analisi puo essere disabilitata."""

    def __init__(self, tree, policy=DEFAULT_POLICY):
        from sparql_analyzer.shared.vocabulary import IDENTIFIER_PREDICATES
        self.tree = tree
        self.nodes = list(walk(tree)) if policy.enabled("algebra_analysis") else []
        self.triples = [t for n in self.nodes if n.get("node") == "BGP" for t in n.get("triples", [])]
        self.graph_vars = set().union(set(), *(variables(n.get("term")) for n in self.nodes if n.get("node") == "Graph"))
        self.sensitive = set()
        if policy.enabled("sensitivity_analysis"):
            self.sensitive.update(self.graph_vars)
            for subject, predicate, obj in self.triples:
                self.sensitive.update(variables(subject))
                if uri(predicate) in IDENTIFIER_PREDICATES:
                    self.sensitive.update(variables(obj))
            self.propagate(self.sensitive, sensitive=True)
        self.numeric = numeric_variables(tree) if policy.enabled("numeric_analysis") else set()
        self.aggregated = set()
        if policy.enabled("aggregate_analysis"):
            for node in self.nodes:
                if node.get("node", "").startswith("Aggregate_"):
                    self.aggregated.update(variables(node.get("res")))
            self.propagate(self.aggregated)
        self.outer_nodes = {id(n) for n in self.outer_walk(tree)}

    @staticmethod
    def outer_walk(value):
        if isinstance(value, dict):
            yield value
            if value.get("node") == "ToMultiSet":
                return
            for key, child in value.items():
                if key != "_vars":
                    yield from QueryAnalysis.outer_walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from QueryAnalysis.outer_walk(child)

    def propagate(self, result, *, sensitive=False):
        while True:
            previous = set(result)
            for node in self.nodes:
                name = node.get("node", "")
                refs = variables(node.get("expr"))
                if name == "Extend" and (bool(refs & result) if sensitive else bool(refs) and refs <= result):
                    result.update(variables(node.get("var")))
                if sensitive and name.startswith("Aggregate_") and name != "Aggregate_Count":
                    if variables(node.get("vars")) & result:
                        result.update(variables(node.get("res")))
            if previous == result:
                return


