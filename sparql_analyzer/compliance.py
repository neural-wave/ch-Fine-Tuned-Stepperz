"""Validatore deterministico e conservativo; non esegue mai la query."""

import argparse
import json
from pathlib import Path

from pyparsing import ParseBaseException
from rdflib.plugins.sparql.parser import parseUpdate
from rdflib.util import from_n3

from .parser import analyze, to_tree
from .expressions import NUMERIC_NODES, NUMERIC_TYPES


PATIENT_PREFIX = "http://example.org/graph/"
ONTOLOGY_GRAPH = "https://biomedit.ch/rdf/sphn-resource/global"
SPHN = "https://biomedit.ch/rdf/sphn-schema/sphn#"
IDENTIFIER_PREDICATES = {
    SPHN + "hasIdentifier", SPHN + "hasSubjectPseudoIdentifier",
}
# Il divieto riguarda i costrutti sintattici espliciti, non le parole nel testo.
# RDFLib puo generare SAMPLE internamente per GROUP BY: non e un SAMPLE utente.
FORBIDDEN_QUERY_NODES = {
    "Aggregate_GroupConcat": "GROUP_CONCAT",
    "Aggregate_Sample": "SAMPLE",
    "Aggregate_Min": "MIN",
    "Aggregate_Max": "MAX",
    "ServiceGraphPattern": "SERVICE",
    "AskQuery": "ASK",
    "ConstructQuery": "CONSTRUCT",
    "DescribeQuery": "DESCRIBE",
}
UPDATE_NODES = {
    "Load": "LOAD", "Clear": "CLEAR", "Drop": "DROP", "Create": "CREATE",
    "Add": "ADD", "Move": "MOVE", "Copy": "COPY",
    "InsertData": "INSERT", "DeleteData": "DELETE", "DeleteWhere": "DELETE",
    "InsertClause": "INSERT", "DeleteClause": "DELETE",
}
ALLOWED_NODES = {
    "SelectQuery", "AskQuery", "ConstructQuery", "DescribeQuery", "Project",
    "Extend", "AggregateJoin", "Aggregate_Count", "Group", "Filter", "Graph",
    "BGP", "Join", "LeftJoin", "Union", "Minus", "Distinct", "Reduced",
    "Slice", "OrderBy", "OrderCondition", "values", "ToMultiSet",
    "TrueFilter", "Builtin_STR", "Builtin_STRSTARTS", "Builtin_BOUND",
    "ConditionalAndExpression", "ConditionalOrExpression", "RelationalExpression",
    "UnaryNot", "AdditiveExpression", "MultiplicativeExpression",
    "Aggregate_Sum", "Aggregate_Avg", "UnaryMinus", "UnaryPlus",
    "Builtin_ABS", "Builtin_ROUND", "Builtin_CEIL", "Builtin_FLOOR",
    "Builtin_isNUMERIC", "Builtin_isIRI", "Builtin_isURI", "Builtin_isBLANK",
    "Builtin_isLITERAL", "Builtin_DATATYPE", "Builtin_LANG", "Builtin_LANGMATCHES",
    "Builtin_STRLEN", "Builtin_LCASE", "Builtin_UCASE", "Builtin_CONTAINS",
    "Builtin_STRENDS", "Builtin_STRBEFORE", "Builtin_STRAFTER", "Builtin_REGEX",
    "Builtin_YEAR", "Builtin_MONTH", "Builtin_DAY", "Builtin_HOURS",
    "Builtin_MINUTES", "Builtin_SECONDS", "Builtin_TZ", "Builtin_TIMEZONE",
    "Builtin_IF", "Builtin_COALESCE", "Builtin_sameTerm",
}
SUPPORTED_AGGREGATES = {"Aggregate_Count", "Aggregate_Sum", "Aggregate_Avg"}
NUMERIC_PREDICATES = {SPHN + "hasValue"}


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

    def numeric(value):
        if isinstance(value, dict):
            if value.get("type") == "Variable":
                return value["value"] in result
            if value.get("type") == "Literal":
                # Il datatype viene verificato sul valore RDF a runtime.
                literal = from_n3(value["value"])
                return str(getattr(literal, "datatype", None)) in NUMERIC_TYPES
            if value.get("node") not in NUMERIC_NODES:
                return False
            return all(numeric(v) for k, v in value.items() if k not in {"node", "_vars", "op"})
        if isinstance(value, list):
            return all(numeric(v) for v in value)
        return False

    for _ in range(len(nodes)):
        for node in nodes:
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


def validate(query):
    findings = []
    forbidden_operators = set()

    def add(rule, reason):
        item = {"code": rule, "reason": reason}
        if item not in findings:
            findings.append(item)

    def finish():
        violations = sorted({f["code"] for f in findings if f["code"].startswith("R")})
        status = "non_compliant" if violations or forbidden_operators else "unsupported" if findings else "compliant"
        return {"is_compliant": not findings, "status": status,
                "violations": violations, "findings": findings,
                "forbidden_operators": sorted(forbidden_operators),
                "policy": "numeric-aggregates-v3"}

    def forbid(operator):
        forbidden_operators.add(operator)
        add("FORBIDDEN_OPERATOR", f"Operatore esplicitamente vietato dalla policy: {operator}.")

    if len(query) > 100_000:
        add("UNSUPPORTED", "Query oltre il limite di 100000 caratteri.")
        return finish()
    try:
        syntax, tree, _ = analyze(query)
    except ParseBaseException as error:
        try:
            update = to_tree(parseUpdate(query))
        except (ParseBaseException, ValueError, TypeError, RecursionError):
            add("SYNTAX", f"Sintassi non supportata o non valida: riga {error.lineno}, colonna {error.col}.")
        else:
            forbid("SPARQL UPDATE")
            for node in walk(update):
                if node.get("node") in UPDATE_NODES:
                    forbid(UPDATE_NODES[node["node"]])
            add("R4", "SPARQL Update non ammesso: sono consentite solo SELECT.")
        return finish()
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as error:
        add("UNSUPPORTED", f"Impossibile analizzare questa struttura: {type(error).__name__}.")
        return finish()

    # L'AST conserva l'operatore scritto dall'utente anche se la traduzione
    # nell'algebra lo riscrive. Commenti, letterali, URI e nomi non sono keyword.
    for node in walk(syntax):
        name = node.get("node")
        if name in FORBIDDEN_QUERY_NODES:
            forbid(FORBIDDEN_QUERY_NODES[name])
        if name == "DatasetClause":
            forbid("FROM NAMED" if "named" in node else "FROM")

    nodes = list(walk(tree))
    if tree.get("node") != "SelectQuery":
        add("R4", "Sono consentite solo query SELECT.")
    sensitive = set()
    graph_vars = set()
    identifier_vars = set()
    triples = []
    for node in nodes:
        name = node.get("node")
        explicitly_forbidden = FORBIDDEN_QUERY_NODES.get(name) in forbidden_operators
        if name and name not in ALLOWED_NODES and not explicitly_forbidden and name != "DatasetClause":
            add("UNSUPPORTED", f"Operatore non verificato dalla policy: {name}.")
        if name == "Graph":
            term = node.get("term")
            graph_vars |= variables(term)
            graph_uri = uri(term)
            if graph_uri and graph_uri != ONTOLOGY_GRAPH:
                add("R1", "Grafo fisso di paziente o grafo non autorizzato.")
        if name == "BGP":
            triples.extend(node.get("triples", []))
        if name == "ToMultiSet" and isinstance(node.get("p"), dict) and node["p"].get("node") != "values":
            add("UNSUPPORTED", "Le sottoquery richiedono analisi separata degli scope.")
        iri = uri(node)
        if iri and iri.startswith(PATIENT_PREFIX):
            add("R1", "La query contiene un riferimento esplicito a un grafo paziente.")

    sensitive |= graph_vars
    if not triples:
        add("UNSUPPORTED", "Manca un pattern clinico verificabile.")
    for triple in triples:
        if len(triple) != 3:
            add("UNSUPPORTED", "Pattern di tripla non riconosciuto.")
            continue
        subject, predicate, obj = triple
        sensitive |= variables(subject)
        if all(isinstance(t, dict) and t.get("type") == "Variable" for t in triple):
            add("R3", "Pattern completamente libero: soggetto, predicato e oggetto variabili.")
        if uri(subject):
            add("R1", "Risorsa soggetto fissa: possibile selezione di un record/paziente identificabile.")
        if uri(predicate) in IDENTIFIER_PREDICATES:
            identifier_vars |= variables(obj)
            sensitive |= variables(obj)
            if not variables(obj):
                add("R1", "Selezione tramite identificatore costante.")
        if not uri(predicate):
            add("UNSUPPORTED", "Predicati variabili o property path non verificati.")
        elif not (uri(predicate).startswith(SPHN) or uri(predicate) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"):
            add("UNSUPPORTED", "Predicato esterno al vocabolario verificato.")

    # Propagazione fino al punto fisso: segue alias anche attraverso piu BIND.
    changed = True
    while changed:
        previous = set(sensitive)
        for node in nodes:
            name = node.get("node", "")
            if name == "Extend" and variables(node.get("expr")) & sensitive:
                sensitive |= variables(node.get("var"))
            if name.startswith("Aggregate_") and name != "Aggregate_Count":
                if variables(node.get("vars")) & sensitive:
                    sensitive |= variables(node.get("res"))
        changed = previous != sensitive

    # Restrizioni su identificatori: anche una trasformazione o un alias resta sensibile.
    for node in nodes:
        name = node.get("node")
        if name == "Filter":
            expr = node.get("expr")
            refs = variables(expr)
            if refs & sensitive:
                # Unica eccezione verificata: selezione dell'intero namespace pazienti.
                allowed = False
                if isinstance(expr, dict) and expr.get("node") == "Builtin_STRSTARTS":
                    arg = expr.get("arg1", {})
                    literal = expr.get("arg2", {})
                    allowed = (arg.get("node") == "Builtin_STR" and
                               variables(arg) <= graph_vars and bool(variables(arg)) and
                               literal.get("type") == "Literal" and
                               literal.get("value") == json.dumps(PATIENT_PREFIX))
                if not allowed:
                    add("R1", "Filtro su risorsa o identificatore individuale, anche tramite alias.")
        if name == "values":
            add("UNSUPPORTED", "VALUES richiede verifica dei vincoli e delle variabili di destinazione.")
        if name == "Extend" and variables(node.get("var")) & sensitive:
            expr = node.get("expr")
            if not variables(expr):
                add("R1", "BIND assegna una costante a una risorsa o identificatore individuale.")
        if name == "Group" and node.get("expr"):
            if variables(node["expr"]) & sensitive:
                add("R1", "Raggruppamento per paziente o risorsa individuale.")
                add("R2", "Statistiche separate per individuo invece di aggregazione di coorte.")
            else:
                add("UNSUPPORTED", "Raggruppamento per categoria non ancora verificato.")

    # SUM/AVG solo su misure note, non su identificatori numerici o risorse.
    numeric = numeric_variables(tree)
    aggregated = set()
    for node in nodes:
        name = node.get("node", "")
        if name in SUPPORTED_AGGREGATES:
            aggregated |= variables(node.get("res"))
            argument = node.get("vars")
            if (name == "Aggregate_Count" and isinstance(argument, dict) and
                    argument.get("type") != "Variable" and variables(argument) & sensitive):
                add("R1", "COUNT con espressione dipendente da risorse o identificatori individuali.")
            if name != "Aggregate_Count":
                refs = variables(node.get("vars"))
                if not refs or not refs <= numeric or refs & sensitive:
                    add("UNSUPPORTED", "SUM/AVG richiedono misure da predicati numerici autorizzati.")
        elif name.startswith("Aggregate_"):
            aggregated |= variables(node.get("res"))
            if FORBIDDEN_QUERY_NODES.get(name) not in forbidden_operators:
                add("UNSUPPORTED", f"Aggregazione non certificata dalla policy iniziale: {name}.")
    changed = True
    while changed:
        previous = set(aggregated)
        for node in nodes:
            if node.get("node") == "Extend":
                refs = variables(node.get("expr"))
                if refs and refs <= aggregated:
                    aggregated |= variables(node.get("var"))
        changed = previous != aggregated
    projected = variables(tree.get("PV", []))
    if tree.get("node") != "SelectQuery" or not projected or not projected <= aggregated:
        add("R2", "L'output non e composto esclusivamente da aggregazioni di coorte verificate.")
    if projected & sensitive:
        add("R5", "Identificatori o risorse individuali raggiungono l'output, anche tramite alias o aggregazione.")
    if tree.get("node") == "ConstructQuery":
        if variables(tree.get("template", [])) & sensitive:
            add("R5", "Il template CONSTRUCT espone risorse individuali.")
    return finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = validate(args.query.read_text(encoding="utf-8-sig"))
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
    return 0 if result["is_compliant"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
