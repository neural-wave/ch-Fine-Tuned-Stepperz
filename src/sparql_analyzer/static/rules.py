"""Regole statiche indipendenti; gli interruttori sono definiti in policy.py."""

import json

from sparql_analyzer.parsing.analysis import walk, variables, uri
from sparql_analyzer.configuration.policy import OPERATOR_CHECKS
from sparql_analyzer.shared.vocabulary import (ALLOWED_NODES, FORBIDDEN_QUERY_NODES, IDENTIFIER_PREDICATES,
                         ONTOLOGY_GRAPH, PATIENT_PREFIX, SPHN, SUPPORTED_AGGREGATES)


class Report:
    def __init__(self, policy):
        self.policy = policy
        self.findings = []
        self.forbidden = set()

    def add(self, check, code, reason):
        if check is not None and not self.policy.enabled(check):
            return
        item = {"code": code, "reason": reason, "check": check}
        if item not in self.findings:
            self.findings.append(item)

    def forbid(self, operator):
        check = OPERATOR_CHECKS[operator]
        if self.policy.enabled(check):
            self.forbidden.add(operator)
            self.add(check, "FORBIDDEN_OPERATOR", f"Operatore esplicitamente vietato dalla policy: {operator}.")

    def result(self):
        violations = sorted({f["code"] for f in self.findings if f["code"].startswith("R")})
        return {"is_compliant": not self.findings,
                "status": "non_compliant" if violations or self.forbidden else "unsupported" if self.findings else "compliant",
                "violations": violations, "findings": self.findings,
                "forbidden_operators": sorted(self.forbidden),
                "policy": "configurable-v6", "configuration": self.policy.to_dict()}


def check_syntax(syntax, analysis, report):
    for node in walk(syntax):
        name = node.get("node")
        if name in FORBIDDEN_QUERY_NODES:
            report.forbid(FORBIDDEN_QUERY_NODES[name])
        if name == "DatasetClause":
            report.forbid("FROM NAMED" if "named" in node else "FROM")
    if analysis.tree.get("node") != "SelectQuery":
        report.add("select_only", "R4", "Sono consentite solo query SELECT.")
    for node in analysis.nodes:
        name = node.get("node")
        # I costrutti riconosciuti hanno divieti dedicati, indipendenti dall'allowlist.
        if name and name not in ALLOWED_NODES and name not in FORBIDDEN_QUERY_NODES and name != "DatasetClause":
            report.add("known_nodes", "UNSUPPORTED", f"Operatore non verificato dalla policy: {name}.")


def check_patterns(analysis, report):
    for node in analysis.nodes:
        if node.get("node") == "Graph":
            graph_uri = uri(node.get("term"))
            if graph_uri and graph_uri != ONTOLOGY_GRAPH:
                report.add("fixed_graph", "R1", "Grafo fisso di paziente o grafo non autorizzato.")
        iri = uri(node)
        if iri and iri.startswith(PATIENT_PREFIX):
            report.add("patient_reference", "R1", "La query contiene un riferimento esplicito a un grafo paziente.")
    if not analysis.triples:
        report.add("clinical_pattern", "UNSUPPORTED", "Manca un pattern clinico verificabile.")
    for subject, predicate, obj in analysis.triples:
        if all(isinstance(t, dict) and t.get("type") == "Variable" for t in (subject, predicate, obj)):
            report.add("unrestricted_triple", "R3", "Pattern completamente libero: soggetto, predicato e oggetto variabili.")
        if uri(subject):
            report.add("fixed_subject", "R1", "Risorsa soggetto fissa: possibile selezione di un record/paziente identificabile.")
        if uri(predicate) in IDENTIFIER_PREDICATES and not variables(obj):
            report.add("constant_identifier", "R1", "Selezione tramite identificatore costante.")
        if not uri(predicate):
            report.add("predicate_shape", "UNSUPPORTED", "Predicati variabili o property path non verificati.")
        elif not (uri(predicate).startswith(SPHN) or uri(predicate) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"):
            report.add("predicate_vocabulary", "UNSUPPORTED", "Predicato esterno al vocabolario verificato.")


def check_sensitive_usage(analysis, report):
    for node in analysis.nodes:
        name = node.get("node")
        if name == "Filter":
            expr = node.get("expr")
            if variables(expr) & analysis.sensitive:
                allowed = False
                if isinstance(expr, dict) and expr.get("node") == "Builtin_STRSTARTS":
                    arg, literal = expr.get("arg1", {}), expr.get("arg2", {})
                    allowed = (arg.get("node") == "Builtin_STR" and
                               variables(arg) <= analysis.graph_vars and bool(variables(arg)) and
                               literal.get("type") == "Literal" and literal.get("value") == json.dumps(PATIENT_PREFIX))
                if not allowed:
                    report.add("sensitive_filter", "R1", "Filtro su risorsa o identificatore individuale, anche tramite alias.")
        if name == "values":
            report.add("values", "UNSUPPORTED", "VALUES richiede verifica dei vincoli e delle variabili di destinazione.")
        if name == "Extend" and variables(node.get("var")) & analysis.sensitive and not variables(node.get("expr")):
            report.add("sensitive_bind", "R1", "BIND assegna una costante a una risorsa o identificatore individuale.")
        if name == "Group" and node.get("expr") and id(node) in analysis.outer_nodes:
            if variables(node["expr"]) & analysis.sensitive:
                report.add("individual_group", "R1", "Raggruppamento per paziente o risorsa individuale.")
                report.add("individual_group", "R2", "Statistiche separate per individuo invece di aggregazione di coorte.")
            else:
                report.add("category_group", "UNSUPPORTED", "Raggruppamento per categoria non ancora verificato.")


def check_aggregates(analysis, report):
    for node in analysis.nodes:
        name = node.get("node", "")
        if name in SUPPORTED_AGGREGATES:
            argument = node.get("vars")
            if (name == "Aggregate_Count" and isinstance(argument, dict) and
                    argument.get("type") != "Variable" and variables(argument) & analysis.sensitive):
                report.add("sensitive_count", "R1", "COUNT con espressione dipendente da risorse o identificatori individuali.")
            if name != "Aggregate_Count":
                refs = variables(argument)
                if not refs or not refs <= analysis.numeric or refs & analysis.sensitive:
                    report.add("numeric_aggregates", "UNSUPPORTED", "SUM/AVG richiedono misure da predicati numerici autorizzati.")
        elif name.startswith("Aggregate_") and name != "Aggregate_Sample":
            if FORBIDDEN_QUERY_NODES.get(name) not in report.forbidden:
                report.add("supported_aggregates", "UNSUPPORTED", f"Aggregazione non certificata dalla policy iniziale: {name}.")


def check_output(analysis, report):
    tree = analysis.tree
    projected = variables(tree.get("PV", []))
    if tree.get("node") != "SelectQuery" or not projected or not projected <= analysis.aggregated:
        report.add("aggregate_output", "R2", "L'output non e composto esclusivamente da aggregazioni di coorte verificate.")
    if projected & analysis.sensitive:
        report.add("sensitive_output", "R5", "Identificatori o risorse individuali raggiungono l'output, anche tramite alias o aggregazione.")
    if tree.get("node") == "ConstructQuery" and variables(tree.get("template", [])) & analysis.sensitive:
        report.add("sensitive_output", "R5", "Il template CONSTRUCT espone risorse individuali.")


def check_correlated_patterns(analysis, report):
    if not report.policy.enabled("privacy_correlated_patterns"):
        return

    def visit(value, in_graph=False):
        if isinstance(value, dict):
            in_graph = in_graph or value.get("node") == "Graph"
            if value.get("node") == "BGP" and value.get("triples") and not in_graph:
                report.add("privacy_correlated_patterns", "R6", "Pattern nel default graph privo di provenienza paziente verificata.")
            for key, child in value.items():
                if key != "_vars":
                    visit(child, in_graph)
        elif isinstance(value, list):
            for child in value:
                visit(child, in_graph)
    visit(analysis.tree)


STATIC_RULES = (check_syntax, check_patterns, check_sensitive_usage, check_aggregates, check_output, check_correlated_patterns)
