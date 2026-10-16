"""Validatore deterministico e conservativo; non esegue mai la query."""

import argparse
import json
from pathlib import Path

from pyparsing import ParseBaseException
from rdflib.plugins.sparql.parser import parseUpdate

from .parser import analyze


PATIENT_PREFIX = "http://example.org/graph/"
ONTOLOGY_GRAPH = "https://biomedit.ch/rdf/sphn-resource/global"
SPHN = "https://biomedit.ch/rdf/sphn-schema/sphn#"
IDENTIFIER_PREDICATES = {
    SPHN + "hasIdentifier", SPHN + "hasSubjectPseudoIdentifier",
}
ALLOWED_NODES = {
    "SelectQuery", "AskQuery", "ConstructQuery", "DescribeQuery", "Project",
    "Extend", "AggregateJoin", "Aggregate_Count", "Group", "Filter", "Graph",
    "BGP", "Join", "LeftJoin", "Union", "Minus", "Distinct", "Reduced",
    "Slice", "OrderBy", "OrderCondition", "values", "ToMultiSet",
    "TrueFilter", "Builtin_STR", "Builtin_STRSTARTS", "Builtin_BOUND",
    "ConditionalAndExpression", "ConditionalOrExpression", "RelationalExpression",
    "UnaryNot", "AdditiveExpression", "MultiplicativeExpression",
}


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

    def add(rule, reason):
        item = {"code": rule, "reason": reason}
        if item not in findings:
            findings.append(item)

    def finish():
        violations = sorted({f["code"] for f in findings if f["code"].startswith("R")})
        status = "non_compliant" if violations else "unsupported" if findings else "compliant"
        return {"is_compliant": not findings, "status": status,
                "violations": violations, "findings": findings,
                "policy": "conservative-count-v1"}

    if len(query) > 100_000:
        add("UNSUPPORTED", "Query oltre il limite di 100000 caratteri.")
        return finish()
    try:
        _, tree, _ = analyze(query)
    except ParseBaseException as error:
        try:
            parseUpdate(query)
        except (ParseBaseException, ValueError, TypeError, RecursionError):
            add("SYNTAX", f"Sintassi non supportata o non valida: riga {error.lineno}, colonna {error.col}.")
        else:
            add("R4", "SPARQL Update non ammesso: sono consentite solo SELECT.")
        return finish()
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as error:
        add("UNSUPPORTED", f"Impossibile analizzare questa struttura: {type(error).__name__}.")
        return finish()

    nodes = list(walk(tree))
    if tree.get("node") != "SelectQuery":
        add("R4", "Sono consentite solo query SELECT.")
    sensitive = set()
    graph_vars = set()
    identifier_vars = set()
    triples = []
    for node in nodes:
        name = node.get("node")
        if name and name not in ALLOWED_NODES:
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
        if node.get("datasetClause"):
            add("UNSUPPORTED", "FROM e FROM NAMED richiedono una policy del dataset dedicata.")
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

    # Solo COUNT globale e proiezioni derivate esclusivamente da conteggi sono approvabili.
    aggregated = set()
    for node in nodes:
        name = node.get("node", "")
        if name == "Aggregate_Count":
            aggregated |= variables(node.get("res"))
        elif name.startswith("Aggregate_"):
            aggregated |= variables(node.get("res"))
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
