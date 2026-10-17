"""API compatibile del validatore; implementazione separata in validation/rules."""
from sparql_analyzer.static.validation import validate
from sparql_analyzer.parsing.analysis import numeric_variables, walk, variables, uri
from sparql_analyzer.shared.vocabulary import (PATIENT_PREFIX, ONTOLOGY_GRAPH, SPHN, IDENTIFIER_PREDICATES,
                         FORBIDDEN_QUERY_NODES, UPDATE_NODES, ALLOWED_NODES,
                         SUPPORTED_AGGREGATES, NUMERIC_PREDICATES)
from sparql_analyzer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
