"""Orchestrazione della validazione statica: parsing, analisi, regole."""

from pyparsing import ParseBaseException
from rdflib.plugins.sparql.parser import parseUpdate

from sparql_analyzer.parsing.analysis import QueryAnalysis, walk
from sparql_analyzer.parsing.parser import analyze, to_tree
from sparql_analyzer.configuration.policy import DEFAULT_POLICY
from sparql_analyzer.static.rules import Report, STATIC_RULES, check_syntax
from sparql_analyzer.shared.vocabulary import UPDATE_NODES


def validate(query, *, policy=DEFAULT_POLICY):
    report = Report(policy)
    if policy.enabled("query_length") and len(query) > policy.max_query_chars:
        report.add("query_length", "UNSUPPORTED", f"Query oltre il limite di {policy.max_query_chars} caratteri.")
        return report.result()
    try:
        syntax, tree, _ = analyze(query, policy=policy)
    except ParseBaseException as error:
        try:
            parsed_update = parseUpdate(query)
            update = to_tree(parsed_update) if policy.enabled("syntax_analysis") else {}
        except (ParseBaseException, ValueError, TypeError, RecursionError):
            report.add(None, "SYNTAX", f"Sintassi non supportata o non valida: riga {error.lineno}, colonna {error.col}.")
        else:
            report.forbid("SPARQL UPDATE")
            for node in walk(update):
                if node.get("node") in UPDATE_NODES:
                    report.forbid(UPDATE_NODES[node["node"]])
            report.add("select_only", "R4", "SPARQL Update non ammesso: sono consentite solo SELECT.")
        return report.result()
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as error:
        report.add(None, "UNSUPPORTED", f"Impossibile analizzare questa struttura: {type(error).__name__}.")
        return report.result()
    analysis = QueryAnalysis(tree, policy)
    for rule in STATIC_RULES:
        if rule is check_syntax:
            rule(syntax, analysis, report)
        else:
            rule(analysis, report)
    return report.result()
