import sys
from pathlib import Path
from sparql_llm.utils import get_schema_for_endpoint

void_path = Path(sys.argv[1]).resolve()
if not void_path.is_file():
    raise SystemExit(f"VoID file not found: {void_path}")

terms = sys.argv[2:] or [
    "OncologyDiagnosis",
    "OncologySurgery",
    "RadiotherapyProcedure",
]

schema = get_schema_for_endpoint(
    "http://offline.invalid/sparql",
    str(void_path),
)

if not schema:
    raise SystemExit("No class/property relationships found in VoID.")

count = 0

for cls, predicates in schema.items():
    if not any(term.lower() in cls.lower() for term in terms):
        continue

    print(f"\nCLASS <{cls}>")
    for predicate, object_types in predicates.items():
        values = ", ".join(object_types) if object_types else "object type unspecified"
        print(f"  <{predicate}> -> {values}")
    count += 1

if count == 0:
    raise SystemExit(
        f"No matching classes found for: {', '.join(terms)}"
    )
