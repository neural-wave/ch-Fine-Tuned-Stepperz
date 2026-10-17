"""SHACL reale, mancata conformita, integrazione con privacy e toggle."""

from pathlib import Path
import pytest
from rdflib import Dataset, Graph, Literal, RDF, RDFS, URIRef, XSD
from sparql_analyzer import DEFAULT_POLICY, Policy, ShaclContext
from sparql_analyzer.adequacy import SH, validate_adequacy
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.privacy_fixture import trusted_context
from tests.shacl_fixture import COUNT, EX, SPHN, cohort, shapes, shacl_context

ADEQUACY = Policy.adequacy()


def test_full_hardened_runs_shacl_and_privacy_and_keeps_numeric_contract():
    data = cohort()
    payload = execute_checked(data, COUNT, policy=Policy.hardened(),
                              context=trusted_context(data), shacl_context=shacl_context())
    assert payload["results"]["bindings"][0]["n"]["value"] == "5"
    assert payload.keys() == {"head", "results"}


def test_adequacy_profile_requires_no_privacy_context():
    data = cohort()
    summary = validate_adequacy(data, shacl_context(), policy=ADEQUACY)
    assert summary.graphs_checked == 5
    assert summary.focus_nodes == 10
    assert execute_checked(data, COUNT, policy=ADEQUACY, shacl_context=shacl_context())


@pytest.mark.parametrize("defect", ["missing", "datatype", "cardinality", "class"])
def test_core_violations_are_blocked_before_query(defect, monkeypatch):
    data = cohort()
    graph = data.graph(URIRef("http://example.org/graph/shacl-0"))
    if defect == "missing":
        graph.remove((EX["diagnosis-0"], SPHN.hasCode, None))
    elif defect == "datatype":
        graph.set((EX["person-0"], SPHN.hasIdentifier, Literal(42)))
    elif defect == "cardinality":
        graph.add((EX["person-0"], SPHN.hasIdentifier, Literal("private-patient@example.invalid")))
    else:
        graph.remove((EX["source-0"], RDF.type, SPHN.SourceSystem))
    def forbidden(*args, **kwargs):
        pytest.fail("La query non deve essere eseguita su dati non adeguati")
    monkeypatch.setattr(data, "query", forbidden)
    with pytest.raises(ResultBlocked, match="non adeguati") as error:
        execute_checked(data, COUNT, policy=ADEQUACY, shacl_context=shacl_context())
    assert "private-patient" not in str(error.value)


def test_independent_graphs_do_not_repair_each_others_missing_type():
    data = cohort()
    graph = data.graph(URIRef("http://example.org/graph/shacl-0"))
    triple = (EX["source-0"], RDF.type, SPHN.SourceSystem)
    graph.remove(triple)
    data.graph(URIRef("http://example.org/graph/shacl-1")).add(triple)
    with pytest.raises(ResultBlocked, match="non adeguati"):
        validate_adequacy(data, shacl_context(), policy=ADEQUACY)


def test_shacl_sparql_constraint_is_executed():
    graph = shapes()
    graph.parse(data='''@prefix sh: <http://www.w3.org/ns/shacl#> .
        <urn:shacl-test:Diagnosis> sh:sparql [ a sh:SPARQLConstraint ;
            sh:message "private-patient@example.invalid" ;
            sh:select "SELECT $this WHERE { $this ?p ?o }" ] .''', format="turtle")
    with pytest.raises(ResultBlocked, match="non adeguati") as error:
        validate_adequacy(cohort(), ShaclContext(graph, inference="none"), policy=ADEQUACY)
    assert "private-patient" not in str(error.value)


def test_sparql_targets_really_activate_constraints_alongside_core_targets():
    graph = shapes()
    graph.parse(data='''@prefix sh: <http://www.w3.org/ns/shacl#> .
        <urn:shacl-test:Advanced> a sh:NodeShape ;
            sh:target [ a sh:SPARQLTarget ;
                sh:select "SELECT ?this WHERE { ?this a <https://biomedit.ch/rdf/sphn-schema/sphn#BilledDiagnosis> }" ] ;
            sh:nodeKind sh:Literal .''', format="turtle")
    # Gli altri target sono validi: non basta verificare almeno un target attivo.
    with pytest.raises(ResultBlocked, match="non adeguati"):
        validate_adequacy(cohort(), ShaclContext(graph, inference="none"), policy=ADEQUACY)


def test_missing_context_fails_closed_and_toggle_really_skips_engine(monkeypatch):
    with pytest.raises(ResultBlocked, match="ShaclContext"):
        execute_checked(cohort(), COUNT, policy=ADEQUACY)
    def forbidden(*args, **kwargs):
        pytest.fail("Motore SHACL disattivato ma invocato")
    monkeypatch.setattr("pyshacl.Validator.run", forbidden)
    assert execute_checked(cohort(), COUNT, policy=ADEQUACY.with_checks(adequacy_shacl=False))


def test_empty_data_is_not_accepted_as_validated():
    with pytest.raises(ResultBlocked, match="Nessun grafo"):
        validate_adequacy(Dataset(), shacl_context(), policy=ADEQUACY)


@pytest.mark.parametrize("target", ["unrelated", "deactivated", "absent-node"])
def test_vacuous_validation_is_blocked_but_target_rule_can_be_disabled(target):
    graph = shapes()
    graph.remove((None, SH.targetClass, None))
    if target == "unrelated":
        graph.add((EX.Diagnosis, SH.targetClass, EX.Unrelated))
    elif target == "deactivated":
        graph.add((EX.Diagnosis, SH.targetClass, SPHN.BilledDiagnosis))
        graph.add((EX.Diagnosis, SH.deactivated, Literal(True)))
    else:
        graph.add((EX.Diagnosis, SH.targetNode, EX.absent))
        graph.remove((EX.Diagnosis, SH.property, None))
    context = ShaclContext(graph, inference="none")
    with pytest.raises(ResultBlocked, match="Nessun target"):
        validate_adequacy(cohort(), context, policy=ADEQUACY)
    assert validate_adequacy(cohort(), context, policy=ADEQUACY.with_checks(adequacy_targets=False))


@pytest.mark.parametrize("severity,flag,other", [
    (SH.Warning, "adequacy_warnings", "adequacy_infos"),
    (SH.Info, "adequacy_infos", "adequacy_warnings"),
])
def test_warning_and_info_toggles_are_independent(severity, flag, other):
    graph = shapes()
    graph.add((EX.SeverityShape, RDF.type, SH.NodeShape))
    graph.add((EX.SeverityShape, SH.targetClass, SPHN.BilledDiagnosis))
    graph.add((EX.SeverityShape, SH.severity, severity))
    graph.add((EX.SeverityShape, SH.nodeKind, SH.Literal))
    context = ShaclContext(graph, inference="none")
    with pytest.raises(ResultBlocked, match="non adeguati"):
        validate_adequacy(cohort(), context, policy=ADEQUACY.with_checks(**{other: False}))
    assert validate_adequacy(cohort(), context, policy=ADEQUACY.with_checks(**{flag: False}))


def test_meta_shapes_is_an_effective_toggle():
    graph = shapes()
    # Un valore di deactivated non booleano e' vietato dal meta-schema.
    graph.add((EX.Broken, RDF.type, SH.NodeShape))
    graph.add((EX.Broken, SH.deactivated, Literal("yes")))
    context = ShaclContext(graph, inference="none")
    with pytest.raises(ResultBlocked, match="Shape SHACL non valide"):
        validate_adequacy(cohort(), context, policy=ADEQUACY)
    assert validate_adequacy(cohort(), context, policy=ADEQUACY.with_checks(adequacy_meta_shapes=False))


def test_engine_failure_is_never_conformity_or_private_error(monkeypatch):
    def failure(*args, **kwargs):
        raise RuntimeError("private-patient@example.invalid")
    monkeypatch.setattr("pyshacl.Validator.run", failure)
    with pytest.raises(ResultBlocked, match="Errore nella validazione SHACL") as error:
        validate_adequacy(cohort(), shacl_context(), policy=ADEQUACY.with_checks(adequacy_meta_shapes=False))
    assert "private-patient" not in str(error.value)
    assert error.value.__suppress_context__


def test_context_copies_graphs_and_rdfs_does_not_mutate_data():
    graph, ontology, data = shapes(), Graph(), cohort()
    for source in data.contexts():
        for node in list(source.subjects(RDF.type, SPHN.BilledDiagnosis)):
            source.set((node, RDF.type, EX.DerivedDiagnosis))
    ontology.add((EX.DerivedDiagnosis, RDFS.subClassOf, SPHN.BilledDiagnosis))
    context = ShaclContext(graph, ontology=ontology, inference="rdfs")
    graph.remove((None, None, None))
    ontology.remove((None, None, None))
    assert validate_adequacy(data, context, policy=ADEQUACY).graphs_checked == 5
    assert all(not list(source.subjects(RDF.type, SPHN.BilledDiagnosis)) for source in data.contexts())
    data.graph(URIRef("http://example.org/graph/shacl-0")).remove((EX["diagnosis-0"], SPHN.hasCode, None))
    with pytest.raises(ResultBlocked, match="non adeguati"):
        validate_adequacy(data, context, policy=ADEQUACY)


def test_shacl_is_independent_of_support_analysis_and_static_approval():
    from sparql_analyzer.compliance import validate
    data = cohort()
    data.graph(URIRef("http://example.org/graph/shacl-0")).remove((EX["diagnosis-0"], SPHN.hasCode, None))
    policy = ADEQUACY.with_checks(support_analysis=False)
    assert validate(COUNT, policy=policy)["is_compliant"]
    with pytest.raises(ResultBlocked, match="non adeguati"):
        execute_checked(data, COUNT, policy=policy, shacl_context=shacl_context())


def test_default_profile_does_not_require_shacl_or_accept_invalid_data_as_certified():
    data = cohort()
    data.graph(URIRef("http://example.org/graph/shacl-0")).remove((EX["diagnosis-0"], SPHN.hasCode, None))
    assert execute_checked(data, COUNT, policy=DEFAULT_POLICY)
    assert validate_adequacy(data, None, policy=DEFAULT_POLICY) is None


def test_mutation_during_query_is_suppressed_even_without_privacy_history(monkeypatch):
    data = cohort()
    original = data.query
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        data.graph(URIRef("http://example.org/graph/shacl-0")).set(
            (EX["person-0"], SPHN.hasIdentifier, Literal(42)))
        return result
    monkeypatch.setattr(data, "query", mutate)
    with pytest.raises(ResultBlocked, match="modificato"):
        execute_checked(data, COUNT, policy=ADEQUACY, shacl_context=shacl_context())


def test_acl_runs_before_shacl_and_failed_shacl_does_not_update_history(monkeypatch):
    from dataclasses import replace
    data = cohort()
    context = trusted_context(data)
    def forbidden(*args, **kwargs):
        pytest.fail("SHACL non deve leggere un dataset fuori ACL")
    with monkeypatch.context() as patch:
        patch.setattr("sparql_analyzer.runtime.validate_adequacy", forbidden)
        with pytest.raises(ResultBlocked, match="autorizzato"):
            execute_checked(data, COUNT, policy=Policy.hardened(),
                            context=replace(context, allowed_graphs=frozenset()), shacl_context=shacl_context())
    data.graph(URIRef("http://example.org/graph/shacl-0")).remove((EX["diagnosis-0"], SPHN.hasCode, None))
    with pytest.raises(ResultBlocked, match="non adeguati"):
        execute_checked(data, COUNT, policy=Policy.hardened(), context=context, shacl_context=shacl_context())
    assert not context.history._records
    assert not context.history._snapshots


def test_repository_sphn_shapes_on_valid_and_invalid_algorithm_with_sparql_targets():
    root = Path(__file__).resolve().parents[1]
    context = ShaclContext.from_files(root / "shacl" / "shacler_shapes.ttl")
    data = Dataset()
    source = URIRef("https://biomedit.ch/rdf/sphn-resource/test-Algorithm-1")
    graph = data.graph(URIRef("http://example.org/graph/official-shapes"))
    graph.add((source, RDF.type, SPHN.Algorithm))
    graph.add((source, SPHN.hasName, Literal("synthetic-algorithm", datatype=XSD.string)))
    assert validate_adequacy(data, context, policy=ADEQUACY).graphs_checked == 1
    graph.set((source, SPHN.hasName, Literal(123)))
    with pytest.raises(ResultBlocked, match="non adeguati"):
        # Stesse shape immutabili: il meta-schema e' gia verificato nel caso valido.
        validate_adequacy(data, context, policy=ADEQUACY.with_checks(adequacy_meta_shapes=False))


def test_context_rejects_empty_shapes_multigraphs_and_unsupported_entailment():
    with pytest.raises(ValueError, match="vuoto"):
        ShaclContext(Graph())
    with pytest.raises(ValueError, match="singolo Graph"):
        ShaclContext(Dataset())
    graph = shapes()
    graph.add((EX.schema, SH.entailment, URIRef("http://www.w3.org/ns/entailment/RDFS")))
    with pytest.raises(ValueError, match="entailment"):
        ShaclContext(graph, inference="none")
    assert ShaclContext(graph, inference="rdfs")


@pytest.mark.parametrize("predicate", [SH.rule, SH.js, SH.expression])
def test_unsupported_advanced_features_are_rejected_instead_of_ignored(predicate):
    graph = shapes()
    graph.add((EX.Diagnosis, predicate, EX.Unsupported))
    with pytest.raises(ValueError, match="non supportata"):
        ShaclContext(graph)
