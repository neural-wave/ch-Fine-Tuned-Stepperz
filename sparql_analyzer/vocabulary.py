"""Vocabolario e operatori riconosciuti; nessuno stato di policy."""

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
    "SelectQuery", "AskQuery", "ConstructQuery", "DescribeQuery", "Project", "Aggregate_Sample",
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


