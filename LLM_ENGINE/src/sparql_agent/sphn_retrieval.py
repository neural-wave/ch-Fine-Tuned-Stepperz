"""Offline SPHN-only retrieval from a declared VoID profile.

The VoID is schema evidence, not observed data or a privacy certification. Query
patterns are generated from that schema; benchmark reference answers are never read.
"""

import math
import re
from collections import Counter
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

SPHN = "https://biomedit.ch/rdf/sphn-schema/sphn#"
TARGET = "http://example.invalid/sphn/sparql"
VOID = "http://rdfs.org/ns/void#"
VOID_EXT = "http://ldf.fi/void-ext#"
STOP = set("the a an of in to for and or by with how what which is are do does it they we our patient patients".split())
ALIASES = {
    "cancer": {"oncology", "neoplasm"},
    "treatment": {"surgery", "radiotherapy", "procedure", "administration"},
    "diagnosed": {"diagnosis", "incidence"},
    "diagnosis": {"diagnosed", "incidence"},
    "radiation": {"radiotherapy"},
}


def words(value: str) -> set[str]:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value).lower()
    tokens = set(re.findall(r"[a-z]{3,}", value)) - STOP
    return tokens | {alias for token in tokens for alias in ALIASES.get(token, ())}


def rank(query: str, rows: list[dict], content) -> list[dict]:
    terms = words(query)
    documents = [words(content(row)) for row in rows]
    frequencies = Counter(token for document in documents for token in document)
    scored = []
    for row, document in zip(rows, documents, strict=True):
        score = sum(math.log(1 + len(rows) / frequencies[token]) for token in terms & document)
        scored.append((score, row))
    return [row for score, row in sorted(scored, key=lambda pair: -pair[0]) if score > 0]


def _rdflib_schema(path: Path) -> dict[str, dict[str, list[str]]]:
    """Offline equivalent of SIB's VoID class/property extraction."""
    graph = Graph().parse(path, format="turtle")
    schema: dict[str, dict[str, list[str]]] = {}
    for partition, _, subject in graph.triples((None, URIRef(VOID + "class"), None)):
        if not str(subject).startswith(SPHN):
            continue
        for property_partition in graph.objects(partition, URIRef(VOID + "propertyPartition")):
            for predicate in graph.objects(property_partition, URIRef(VOID + "property")):
                if not isinstance(predicate, URIRef):
                    continue
                values = schema.setdefault(str(subject), {}).setdefault(str(predicate), [])
                for object_partition in graph.objects(property_partition, URIRef(VOID + "classPartition")):
                    values.extend(str(value) for value in graph.objects(object_partition, URIRef(VOID + "class")))
                for datatype_partition in graph.objects(property_partition, URIRef(VOID_EXT + "datatypePartition")):
                    values.extend(str(value) for value in graph.objects(datatype_partition, URIRef(VOID_EXT + "datatype")))
    return {cls: {pred: sorted(set(values)) for pred, values in predicates.items()}
            for cls, predicates in schema.items()}


def load_schema(path: Path) -> dict[str, dict[str, list[str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"SPHN VoID file not found: {path}")
    # Use SIB's parser when its optional indexer dependencies are installed. The
    # fallback uses the same local VoID relationships without contacting an endpoint.
    try:
        from sparql_llm.utils import get_schema_for_endpoint
    except ImportError:
        schema = _rdflib_schema(path)
    else:
        schema = get_schema_for_endpoint(TARGET, str(path))
    schema = {cls: predicates for cls, predicates in schema.items() if cls.startswith(SPHN)}
    if not schema:
        raise ValueError("SPHN VoID yielded no SPHN class/property relationships")
    return schema


def _term(iri: str) -> str:
    if iri.startswith(SPHN):
        return "sphn:" + iri[len(SPHN):]
    if iri.startswith("http://www.w3.org/2001/XMLSchema#"):
        return "xsd:" + iri.rsplit("#", 1)[1]
    return f"<{iri}>"


def _value_type(iri: str) -> str:
    """VoID range classes describe the object's rdf:type, not a fixed object IRI."""
    if iri.startswith("http://www.w3.org/2001/XMLSchema#") or iri == "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString":
        return _term(iri)
    return "{ a [ " + _term(iri) + " ] }"


class SphnVoidRetrieval:
    def __init__(self, void_file: Path, ontology_file: Path | None = None):
        self.void_file = void_file
        schema = load_schema(void_file)
        labels = {}
        if ontology_file and ontology_file.is_file():
            graph = Graph().parse(ontology_file, format="turtle")
            labels = {str(subject): str(label) for subject, label in graph.subject_objects(RDFS.label)}
        self.classes = []
        self.examples = []
        for iri, predicates in sorted(schema.items()):
            label = labels.get(iri, iri[len(SPHN):])
            lines = [f"shape:{iri[len(SPHN):]} {{", f"  a [ {_term(iri)} ] ;"]
            for predicate, values in sorted(predicates.items()):
                alternatives = [_value_type(value) for value in values]
                value_text = ("(" + " OR ".join(alternatives) + ")" if len(alternatives) > 1
                              else alternatives[0] if alternatives else "IRI")
                lines.append(f"  {_term(predicate)} {value_text} ;")
            lines[-1] = lines[-1].rstrip(" ;")
            lines.append("}")
            self.classes.append({"label": label, "iri": iri, "shex": "\n".join(lines),
                                 "declared_value_types": predicates,
                                 "schema_notes": "VoID lists range classes/datatypes, not fixed data values or terminology codes. "
                                                 "A coding-system class IRI is not a diagnosis code. "
                                                 "Retrieve every class needed for the requested join; do not invent predicates.",
                                 "endpoint_url": TARGET})
            # An aggregate pattern does not return patient identifiers or individual rows.
            # It is derived solely from VoID, never from benchmark reference answers.
            for predicate in sorted(predicates):
                if not predicate.startswith(SPHN):
                    continue
                question = f"Count {label} records with {predicate[len(SPHN):]}"
                query = (f"#+ endpoint: {TARGET}\nPREFIX sphn: <{SPHN}>\n"
                         "SELECT (COUNT(DISTINCT ?record) AS ?record_count) WHERE {\n"
                         f"  GRAPH ?g {{ ?record a {_term(iri)} ; {_term(predicate)} ?value . }}\n"
                         "}")
                self.examples.append({"question": question, "query": query,
                                      "endpoint_url": TARGET, "source": "void_schema_aggregate_pattern",
                                      "class_iri": iri, "predicate_iri": predicate})
        if not self.examples:
            raise ValueError("SPHN VoID yielded no SPHN query patterns")

    def search_sparql_classes(self, classes: list[str]) -> dict:
        selected = []
        seen = set()
        for term in classes[:6]:
            exact = [row for row in self.classes
                     if term in {row["iri"], row["iri"].rsplit("#", 1)[-1], _term(row["iri"])}]
            candidates = exact or rank(term, self.classes, lambda item: item["label"] + " " + item["iri"])[:2]
            for row in candidates:
                if row["iri"] not in seen:
                    selected.append(row)
                    seen.add(row["iri"])
        return {"classes_schemas": selected[:6]}

    def search_sparql_examples(self, question: str, steps: list[str]) -> dict:
        prompt = question + " " + " ".join(steps)
        explicit = set(re.findall(r"[a-z]{3,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", prompt).lower()))
        ordered_classes = rank(prompt, self.classes, lambda item: item["label"] + " " + item["iri"])
        ordered_classes.sort(key=lambda item: -(
            len(explicit & words(item["label"]))
            + (2 if "cancer" in explicit and "Oncology" in item["iri"] else 0)
            + (2 if any(term in explicit and term in item["iri"].lower()
                        for term in ("surgery", "radiotherapy")) else 0)
        ))
        selected = []
        for cls in ordered_classes:
            patterns = [row for row in self.examples if row["class_iri"] == cls["iri"]]
            preferred = ("hasIncidenceDateTime" if "Diagnosis" in cls["iri"] else
                         "hasStartDateTime" if any(term in cls["iri"] for term in ("Surgery", "Radiotherapy")) else "")
            patterns.sort(key=lambda row: (row["predicate_iri"].endswith(preferred) if preferred else False), reverse=True)
            row = patterns[0]
            selected.append({key: row[key] for key in ("question", "query", "endpoint_url", "source", "class_iri")})
            if len(selected) == 3:
                break
        return {"query_examples": selected}


def build_server(retrieval: SphnVoidRetrieval) -> MCPServer:
    server = MCPServer("Local SPHN VoID retrieval (no execution)", log_level="WARNING")

    @server.tool()
    def search_sparql_examples(question: str, steps: list[str]) -> dict:
        """Find SPHN aggregate query patterns derived from local VoID declarations. Patterns are not compliance certifications."""
        return retrieval.search_sparql_examples(question, steps)

    @server.tool()
    def search_sparql_classes(classes: list[str]) -> dict:
        """Find SPHN class predicates and declared value types in ShEx-like form from local VoID."""
        return retrieval.search_sparql_classes(classes)

    return server
