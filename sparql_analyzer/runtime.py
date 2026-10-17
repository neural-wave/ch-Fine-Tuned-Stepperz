"""API di esecuzione: policy per richiesta e selezione del valutatore."""
import json
from pyparsing import ParseBaseException
from .parser import analyze
from .policy import DEFAULT_POLICY
from .validation import validate
from .results import ResultBlocked, UnsupportedExecution, check_payload, number, nodes
from .algebra import count_variables
from .privacy import ExecutionContext, ReleaseHistory, preflight, snapshot_digest
from contextlib import nullcontext
from .adequacy import validate_adequacy


def execute_checked(dataset, query, *, policy=DEFAULT_POLICY, min_patients=None, max_support_rows=None, context=None, shacl_context=None):
    """Esegue con contesto fidato opzionale e transazione sullo storico."""
    try:
        preflight(dataset, policy, context)
        use_history = policy.enabled("privacy_query_history") or policy.enabled("privacy_temporal_history")
        with context.history.locked() if use_history else nullcontext():
            check_snapshot = use_history or policy.enabled("adequacy_shacl")
            fingerprint = snapshot_digest(dataset) if check_snapshot else None
            if policy.enabled("privacy_temporal_history"):
                context.history.check_snapshot(context.dataset_id, fingerprint)
            validate_adequacy(dataset, shacl_context, policy=policy)
            cohorts = []
            payload = _execute_checked(dataset, query, policy=policy, min_patients=min_patients,
                                       max_support_rows=max_support_rows, context=context, cohorts=cohorts)
            if check_snapshot:
                if snapshot_digest(dataset) != fingerprint:
                    raise ResultBlocked("Dataset modificato durante i controlli: risultato soppresso.")
            if use_history:
                context.history.record(dataset_id=context.dataset_id, fingerprint=fingerprint,
                    query=query, cohorts=cohorts, min_patients=policy.min_patients if min_patients is None else min_patients,
                    check_queries=policy.enabled("privacy_query_history"), check_temporal=policy.enabled("privacy_temporal_history"))
            return payload
    except ResultBlocked:
        raise
    except Exception:
        if policy.enabled("privacy_normalize_errors"):
            raise ResultBlocked("Errore durante l'esecuzione verificata: risultato non disponibile.") from None
        raise


def _execute_checked(dataset, query, *, policy, min_patients, max_support_rows, context, cohorts):
    min_patients = policy.min_patients if min_patients is None else min_patients
    max_support_rows = policy.max_support_rows if max_support_rows is None else max_support_rows
    if type(min_patients) is not int or min_patients < 2:
        raise ValueError("min_patients deve essere un intero >= 2")
    if type(max_support_rows) is not int or max_support_rows < 1:
        raise ValueError("max_support_rows deve essere positivo")
    if not validate(query, policy=policy)["is_compliant"]:
        raise ResultBlocked("Query bloccata dal controllo statico.")
    try:
        _, tree, prepared = analyze(query, policy=policy)
    except ParseBaseException as error:
        raise UnsupportedExecution("execute_checked non esegue SPARQL Update; la policy statica non estende il motore.") from error
    if prepared.algebra.name not in {"SelectQuery", "AskQuery"}:
        raise UnsupportedExecution("execute_checked restituisce SPARQL Results JSON: sono eseguibili SELECT e ASK; il motore non esporta grafi RDF.")
    if not policy.enabled("support_analysis"):
        payload = json.loads(dataset.query(prepared, use_store_provided=False).serialize(format="json"))
        columns = [str(v) for v in prepared.algebra.get("PV", [])]
        counts = {str(v) for v in count_variables(prepared.algebra)} if policy.enabled("count_format") else set()
        check_payload(payload, columns, numeric_columns=set(columns) - counts, policy=policy)
        return payload
    all_nodes = list(nodes(prepared.algebra))
    nested = any(n.name == "ToMultiSet" and any(child.name == "AggregateJoin" for child in nodes(n["p"]))
                 for n in all_nodes)
    privacy_provenance = any(policy.enabled(name) for name in (
        "privacy_effective_contributors", "privacy_distinct_persons", "privacy_query_history"))
    if nested or privacy_provenance or any(not policy.enabled(name) for name in (
            "runtime_single_graph", "runtime_global_group", "runtime_expressions",
            "runtime_distinct_star", "runtime_aggregates")):
        from .nested import execute_nested
        return execute_nested(dataset, prepared, tree=tree, policy=policy, min_patients=min_patients,
                              max_support_rows=max_support_rows, execution_context=context, released_cohorts=cohorts)
    from .flat import execute_flat
    return execute_flat(dataset, tree, prepared, policy=policy, min_patients=min_patients,
                        max_support_rows=max_support_rows)
