"""API compatibile del validatore; implementazione separata in validation/rules."""
from .validation import validate
from .analysis import numeric_variables, walk, variables, uri
from .vocabulary import (PATIENT_PREFIX, ONTOLOGY_GRAPH, SPHN, IDENTIFIER_PREDICATES,
                         FORBIDDEN_QUERY_NODES, UPDATE_NODES, ALLOWED_NODES,
                         SUPPORTED_AGGREGATES, NUMERIC_PREDICATES)
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
