"""Adeguatezza dei dati RDF: shape fidate, grafi separati, nessun report pubblico.

Il motore e' pySHACL 0.25, fissato per compatibilita con RDFLib 6.3.2.
Le API Shape/Validator del motore permettono di verificare i target effettivi
sullo stesso grafo inferito usato per i vincoli, senza simulare i target SHACL.
"""

from dataclasses import dataclass
import logging
from pathlib import Path

from rdflib import ConjunctiveGraph, Graph, Namespace, RDF, URIRef

from sparql_analyzer.configuration.policy import DEFAULT_POLICY
from sparql_analyzer.shared.results import ResultBlocked

SH = Namespace("http://www.w3.org/ns/shacl#")
RDFS_ENTAILMENT = URIRef("http://www.w3.org/ns/entailment/RDFS")


def _triples(graph, name):
    if not isinstance(graph, Graph) or isinstance(graph, ConjunctiveGraph):
        raise ValueError(f"{name} deve essere un singolo Graph RDFLib locale")
    return tuple(graph)


def _graph(triples):
    graph = Graph()
    for triple in triples:
        graph.add(triple)
    return graph


@dataclass(frozen=True, init=False)
class ShaclContext:
    """Copia immutabile di shape/ontologia scelte dal servizio, mai dalla query."""

    _shapes: tuple
    _ontology: tuple | None
    inference: str

    def __init__(self, shapes, *, ontology=None, inference="rdfs"):
        if inference not in {"none", "rdfs"}:
            raise ValueError("Inferenza SHACL supportata: none oppure rdfs")
        shape_triples = _triples(shapes, "shapes")
        if not shape_triples:
            raise ValueError("Il grafo delle shape non puo essere vuoto")
        regimes = set(shapes.objects(None, SH.entailment))
        if regimes - {RDFS_ENTAILMENT} or (regimes and inference != "rdfs"):
            raise ValueError("Regime sh:entailment non supportato dalla configurazione")
        # Attiviamo SHACL-AF solo per i target SPARQL usati dal file SPHN.
        # Le altre funzionalita non devono essere ignorate o eseguire regole.
        forbidden_predicates = (SH.rule, SH.js, SH.expression, SH.values)
        forbidden_types = (SH.SPARQLFunction, SH.JSFunction, SH.JSConstraint,
                           SH.JSTarget, SH.JSTargetType, SH.SPARQLTargetType)
        if (any((None, predicate, None) in shapes for predicate in forbidden_predicates)
                or any((None, RDF.type, kind) in shapes for kind in forbidden_types)
                or any((target, RDF.type, SH.SPARQLTarget) not in shapes
                       for target in shapes.objects(None, SH.target))):
            raise ValueError("Funzionalita SHACL avanzata non supportata: ammissibili soltanto target SPARQL diretti")
        object.__setattr__(self, "_shapes", shape_triples)
        object.__setattr__(self, "_ontology", None if ontology is None else _triples(ontology, "ontology"))
        object.__setattr__(self, "inference", inference)

    @classmethod
    def from_files(cls, shapes_path, *, ontology_path=None, inference="rdfs"):
        """Legge soltanto file Turtle locali; nessun import OWL o URL implicito."""
        def load(path):
            local = Path(path)
            if not local.is_file():
                raise ValueError("File Turtle locale non disponibile")
            return Graph().parse(data=local.read_text(encoding="utf-8-sig"), format="turtle")
        return cls(load(shapes_path), ontology=None if ontology_path is None else load(ontology_path), inference=inference)


@dataclass(frozen=True)
class AdequacySummary:
    """Solo diagnostica interna aggregata; mai aggiunta alla risposta SPARQL."""

    graphs_checked: int
    focus_nodes: int


def validate_adequacy(dataset, context, *, policy=DEFAULT_POLICY):
    """Solleva ResultBlocked se dati, target o motore non soddisfano la policy.

    Non unisce named graph: una risorsa di un altro paziente non puo riparare
    un collegamento mancante. Il fingerprint prima/dopo e' gestito dal runtime.
    Warning/Info rimangono distinti dal concetto di conformita dello standard:
    consentirli e' una decisione operativa esplicita della policy.
    """
    if not policy.enabled("adequacy_shacl"):
        return None
    if not isinstance(context, ShaclContext):
        raise ResultBlocked("La policy di adeguatezza richiede ShaclContext fidato.")
    try:
        from pyshacl import Validator
        from pyshacl.validate import meta_validate

        logger = logging.Logger("sparql_analyzer.adequacy")
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        shapes = _graph(context._shapes)
        if policy.enabled("adequacy_meta_shapes"):
            conforms, report, _ = meta_validate(shapes, inference="none", logger=logger)
            if conforms is not True or not isinstance(report, Graph):
                raise ResultBlocked("Shape SHACL non valide: risultato soppresso.")
        graphs = [g for g in dataset.contexts() if len(g)]
        if not graphs:
            raise ResultBlocked("Nessun grafo dati da validare con SHACL.")
        focus_count = 0
        for source in graphs:
            # Anche senza inferenza il motore riceve copie, mai il Dataset live.
            data = _graph(tuple(source))
            validator = Validator(data, shacl_graph=_graph(context._shapes),
                ont_graph=None if context._ontology is None else _graph(context._ontology),
                options={"inference": context.inference, "advanced": True,
                         "use_js": False, "iterate_rules": False, "debug": False,
                         "allow_warnings": False, "allow_infos": False,
                         "logger": logger})
            conforms, report, _ = validator.run()
            if not isinstance(report, Graph) or type(conforms) is not bool:
                raise ResultBlocked("Report SHACL non valido: risultato soppresso.")
            results = list(report.subjects(RDF.type, SH.ValidationResult))
            blocked_severities = {SH.Violation}
            if policy.enabled("adequacy_warnings"):
                blocked_severities.add(SH.Warning)
            if policy.enabled("adequacy_infos"):
                blocked_severities.add(SH.Info)
            severities = [set(report.objects(result, SH.resultSeverity)) for result in results]
            if (not conforms and not results) or any(
                len(severity) != 1 or not severity <= {SH.Violation, SH.Warning, SH.Info}
                or severity & blocked_severities for severity in severities
            ):
                raise ResultBlocked("Dati non adeguati alle shape SHACL: risultato soppresso.")
            if policy.enabled("adequacy_targets"):
                focus = set()
                for shape in validator.shacl_graph.shapes:
                    if not shape.deactivated:
                        focus.update(shape.focus_nodes(validator.target_graph))
                # I target devono raggiungere dati reali del grafo originale,
                # non soltanto risorse dell'ontologia o nodi target inesistenti.
                data_nodes = set(source.subjects()) | set(source.objects())
                focus.intersection_update(data_nodes)
                if not focus:
                    raise ResultBlocked("Nessun target SHACL effettivo nel grafo dati: risultato soppresso.")
                focus_count += len(focus)
        return AdequacySummary(len(graphs), focus_count)
    except ResultBlocked:
        raise
    except Exception:
        # Report, focusNode, value e messaggi del motore possono contenere PHI.
        raise ResultBlocked("Errore nella validazione SHACL: risultato soppresso.") from None
