#!/usr/bin/env python3
"""
Genera un file VoID dai dati dei pazienti in Virtuoso, nel formato letto da sparql-llm
(https://github.com/sib-swiss/sparql-llm): SparqlVoidShapesLoader, get_schema_for_endpoint,
validate_sparql_with_void.

Perche' non void-generator: i dati SPHN hanno un named graph per paziente, e void-generator
fa query separate per ogni combinazione di classi e grafi (milioni di query). Qui bastano
poche query aggregate, eseguite da Virtuoso in un'unica passata.

Cosa produce:
  data/void.ttl          VoID: per ogni classe, le proprieta' usate e verso quali classi o
                         tipi di dato puntano (void:classPartition / void:propertyPartition /
                         void-ext:datatypePartition), piu' il numero di istanze (void:entities)
  data/void_schema.json  lo stesso contenuto come dizionario {classe: {proprieta': [tipi]}},
                         il formato che validate_sparql_with_void accetta in endpoints_void_dict

Uso:
  pip install requests rdflib
  python build_void.py                          # tutti i pazienti caricati
  python build_void.py --sample 10 --out data/void_10.ttl
  python build_void.py --endpoint http://localhost:8890/sparql --out data/void.ttl

Scelte:
  * Le classi dei codici medici (ICD-10-GM, CHOP, SNOMED, LOINC, ...) vengono raggruppate per
    terminologia: invece di migliaia di classi "icd-10-gm:E11", "icd-10-gm:A00", ... il VoID
    contiene una sola pseudo-classe "https://biomedit.ch/rdf/sphn-resource/icd-10-gm/".
    I codici precisi li fornisce l'indice dei codici, non il VoID. Disattivabile con --keep-codes.
  * Gli oggetti senza tipo nel grafo del paziente (es. sphn-individual:Principal per hasRank)
    vengono tipizzati cercando il loro tipo nel grafo delle ontologie.
  * Le classi dei codici compaiono anche come soggetti, con le loro proprieta': cosi' il
    validatore sa quali proprieta' puo' avere una variabile che punta a un codice.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import requests

SPHN = "https://biomedit.ch/rdf/sphn-schema/sphn#"
GLOBAL = "https://biomedit.ch/rdf/sphn-resource/global"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
# tipi "tecnici" da ignorare quando tipizziamo gli oggetti tramite le ontologie
IGNORED_TYPE_NS = (
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
)
DATATYPE_NS = ("http://www.w3.org/2001/XMLSchema#", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
PAGE = 10000  # righe massime per risposta dell'endpoint SPARQL di Virtuoso


# ---------------------------------------------------------------- esecuzione delle query

class Endpoint:
    def __init__(self, url, timeout=3600):
        self.url, self.timeout = url, timeout

    def select(self, query):
        r = requests.post(self.url, data={"query": query},
                          headers={"Accept": "application/sparql-results+json"},
                          timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Errore {r.status_code} dall'endpoint:\n{r.text[:2000]}")
        return [{k: v["value"] for k, v in row.items()}
                for row in r.json()["results"]["bindings"]]

    def select_all(self, query, order_by):
        """Legge a pagine, perche' Virtuoso restituisce al massimo 10.000 righe per risposta."""
        rows, offset = [], 0
        while True:
            page = self.select(f"{query}\nORDER BY {order_by}\nLIMIT {PAGE} OFFSET {offset}")
            rows.extend(page)
            if len(page) < PAGE:
                return rows
            offset += PAGE


# ---------------------------------------------------------------- query

def graph_scope(graphs):
    """Vincola ?g ai grafi scelti, oppure a tutti tranne quello delle ontologie."""
    if graphs:
        return "VALUES ?g { " + " ".join(f"<{g}>" for g in graphs) + " }"
    return f"FILTER (?g != <{GLOBAL}>)"


def q_typed_links(scope):
    # classe del soggetto, proprieta', classe dell'oggetto (se l'oggetto ha un tipo nel grafo)
    return f"""
SELECT DISTINCT ?c ?p ?oc WHERE {{
  {scope}
  GRAPH ?g {{
    ?s a ?c ;
       ?p ?o .
    ?o a ?oc .
  }}
  FILTER (?p != <{RDF_TYPE}>)
}}"""


def q_datatypes(scope):
    # classe del soggetto, proprieta', tipo di dato dei letterali
    return f"""
SELECT DISTINCT ?c ?p ?dt WHERE {{
  {scope}
  GRAPH ?g {{
    ?s a ?c ;
       ?p ?o .
  }}
  FILTER (isLiteral(?o))
  BIND (DATATYPE(?o) AS ?dt)
}}"""


def q_untyped_objects(scope):
    # oggetti IRI senza tipo nel grafo del paziente: cerchiamo il tipo nelle ontologie
    return f"""
SELECT DISTINCT ?c ?p ?oc WHERE {{
  {scope}
  GRAPH ?g {{
    ?s a ?c ;
       ?p ?o .
    FILTER (isIRI(?o))
    FILTER NOT EXISTS {{ ?o a ?anytype }}
  }}
  FILTER (?p != <{RDF_TYPE}>)
  OPTIONAL {{ GRAPH <{GLOBAL}> {{ ?o a ?oc . }} }}
}}"""


def q_class_counts(scope):
    return f"""
SELECT ?c (COUNT(DISTINCT ?s) AS ?n) WHERE {{
  {scope}
  GRAPH ?g {{ ?s a ?c . }}
}}
GROUP BY ?c"""


# ---------------------------------------------------------------- costruzione dello schema

def collapse(iri, keep_codes):
    """I codici delle terminologie diventano la loro terminologia (namespace)."""
    if keep_codes or iri.startswith(SPHN):
        return iri
    cut = max(iri.rfind("/"), iri.rfind("#"))
    return iri[:cut + 1] if cut > 0 else iri


def build_schema(ep, graphs, keep_codes, log):
    scope = graph_scope(graphs)
    schema = defaultdict(lambda: defaultdict(set))  # classe -> proprieta' -> {tipi}

    log("1/4 collegamenti tra classi...")
    for r in ep.select_all(q_typed_links(scope), "?c ?p ?oc"):
        schema[collapse(r["c"], keep_codes)][r["p"]].add(collapse(r["oc"], keep_codes))

    log("2/4 tipi di dato dei valori...")
    for r in ep.select_all(q_datatypes(scope), "?c ?p ?dt"):
        props = schema[collapse(r["c"], keep_codes)][r["p"]]
        if r.get("dt", "").startswith(DATATYPE_NS):
            props.add(r["dt"])

    log("3/4 oggetti senza tipo (cerco il tipo nelle ontologie)...")
    for r in ep.select_all(q_untyped_objects(scope), "?c ?p ?oc"):
        props = schema[collapse(r["c"], keep_codes)][r["p"]]  # la proprieta' esiste comunque
        oc = r.get("oc")
        if oc and not oc.startswith(IGNORED_TYPE_NS):
            props.add(collapse(oc, keep_codes))

    log("4/4 numero di istanze per classe...")
    counts = defaultdict(int)
    for r in ep.select_all(q_class_counts(scope), "?c"):
        counts[collapse(r["c"], keep_codes)] += int(r["n"])

    return schema, counts


# ---------------------------------------------------------------- scrittura

def write_void(schema, counts, path, void_iri):
    lines = [
        "@prefix void: <http://rdfs.org/ns/void#> .",
        "@prefix void-ext: <http://ldf.fi/void-ext#> .",
        "",
        f"<{void_iri}> a void:Dataset .",
        "",
    ]
    for i, cls in enumerate(sorted(schema)):
        cp = f"_:cp{i}"
        lines.append(f"<{void_iri}> void:classPartition {cp} .")
        lines.append(f"{cp} void:class <{cls}> .")
        if counts.get(cls):
            lines.append(f"{cp} void:entities {counts[cls]} .")
        for j, (prop, targets) in enumerate(sorted(schema[cls].items())):
            pp = f"_:pp{i}_{j}"
            lines.append(f"{cp} void:propertyPartition {pp} .")
            lines.append(f"{pp} void:property <{prop}> .")
            for t in sorted(targets):
                if t.startswith(DATATYPE_NS):
                    lines.append(f"{pp} void-ext:datatypePartition [ void-ext:datatype <{t}> ] .")
                else:
                    lines.append(f"{pp} void:classPartition [ void:class <{t}> ] .")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def as_schema_dict(schema):
    """Formato di sparql-llm: {classe: {proprieta': [classi o tipi di dato]}}."""
    return {c: {p: sorted(t) for p, t in sorted(props.items())} for c, props in sorted(schema.items())}


# ---------------------------------------------------------------- verifica

# Stessa query che usa sparql-llm (sparql_llm.utils.GET_VOID_DESC) per leggere un VoID
SPARQL_LLM_VOID_QUERY = """
PREFIX void: <http://rdfs.org/ns/void#>
PREFIX void-ext: <http://ldf.fi/void-ext#>
SELECT DISTINCT ?subjectClass ?prop ?objectClass ?objectDatatype
WHERE {
  {
    ?cp void:class ?subjectClass ;
        void:propertyPartition ?pp .
    ?pp void:property ?prop .
    OPTIONAL {
      { ?pp void:classPartition [ void:class ?objectClass ] . }
      UNION
      { ?pp void-ext:datatypePartition [ void-ext:datatype ?objectDatatype ] . }
    }
  } UNION {
    ?linkset void:subjectsTarget [ void:class ?subjectClass ] ;
             void:linkPredicate ?prop ;
             void:objectsTarget [ void:class ?objectClass ] .
  }
}"""


def verify(path, expected):
    """Rilegge il file come lo legge sparql-llm e controlla che ritrovi tutto."""
    import rdflib
    g = rdflib.Graph()
    g.parse(path, format="turtle")
    found = defaultdict(lambda: defaultdict(set))
    for s, p, oc, dt in g.query(SPARQL_LLM_VOID_QUERY):
        targets = found[str(s)][str(p)]
        for t in (oc, dt):
            if t is not None:
                targets.add(str(t))
    found = {c: {p: sorted(t) for p, t in props.items()} for c, props in found.items()}
    return found == expected


# ---------------------------------------------------------------- main

def pick_graphs(args):
    if not args.sample:
        return None
    files = sorted(Path(args.patients_dir).glob("*.ttl"))[: args.sample]
    if not files:
        sys.exit(f"Nessun file .ttl in {args.patients_dir}")
    return [args.graph_prefix + f.stem for f in files]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", default="http://localhost:8890/sparql")
    ap.add_argument("--out", default="data/void.ttl")
    ap.add_argument("--json", default=None, help="default: accanto al .ttl, con nome *_schema.json")
    ap.add_argument("--sample", type=int, default=0, help="usa solo i primi N pazienti (0 = tutti)")
    ap.add_argument("--patients-dir", default="patients")
    ap.add_argument("--graph-prefix", default="http://example.org/graph/")
    ap.add_argument("--void-iri", default="http://localhost:8890/.well-known/void")
    ap.add_argument("--keep-codes", action="store_true", help="non raggruppare i codici per terminologia")
    args = ap.parse_args()

    out = Path(args.out)
    json_path = Path(args.json) if args.json else out.with_name(out.stem + "_schema.json")
    graphs = pick_graphs(args)
    print(f"Endpoint: {args.endpoint} | pazienti: {len(graphs) if graphs else 'tutti'}")

    schema, counts = build_schema(Endpoint(args.endpoint), graphs, args.keep_codes, print)
    if not schema:
        sys.exit("Nessuna classe trovata: controlla che Virtuoso sia acceso e i pazienti caricati.")

    write_void(schema, counts, out, args.void_iri)
    expected = as_schema_dict(schema)
    json_path.write_text(json.dumps(expected, indent=1))

    sphn = [c for c in schema if c.startswith(SPHN)]
    pairs = sum(len(schema[c]) for c in sphn)
    print(f"\nScritto {out} e {json_path}")
    print(f"  classi SPHN: {len(sphn)}  | coppie classe-proprieta' SPHN: {pairs}")
    print(f"  pseudo-classi delle terminologie: {len(schema) - len(sphn)}")
    for c in sorted(sphn, key=lambda c: -counts.get(c, 0))[:5]:
        print(f"    {c.replace(SPHN, 'sphn:')}: {counts.get(c, 0)} istanze, {len(schema[c])} proprieta'")

    try:
        ok = verify(out, expected)
        print("\nVerifica con la query di sparql-llm:", "OK" if ok else "DIFFERENZE (segnalalo)")
    except ImportError:
        print("\n(installa rdflib per la verifica automatica)")


if __name__ == "__main__":
    main()