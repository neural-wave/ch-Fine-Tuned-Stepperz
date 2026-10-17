"""Contesto fidato e storico dei rilasci per le policy di privacy opt-in.

Non deriva identita o autorizzazioni dal testo della query. Lo storico deve
essere condiviso dal servizio per la stessa popolazione protetta.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from .results import ResultBlocked


@dataclass(frozen=True)
class ExecutionContext:
    principal_id: str
    dataset_id: str
    allowed_graphs: frozenset[str] = field(default_factory=frozenset)
    graph_patients: Mapping[str, str] = field(default_factory=dict)
    history: "ReleaseHistory | None" = None

    def __post_init__(self):
        if not isinstance(self.principal_id, str) or not self.principal_id.strip():
            raise ValueError("principal_id deve essere una stringa non vuota")
        if not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise ValueError("dataset_id deve essere una stringa non vuota")
        if isinstance(self.allowed_graphs, str):
            raise ValueError("allowed_graphs deve essere una collezione di URI")
        object.__setattr__(self, "allowed_graphs", frozenset(str(g) for g in self.allowed_graphs))
        mapping = {str(g): p for g, p in self.graph_patients.items()}
        if any(not isinstance(p, str) or not p for p in mapping.values()):
            raise ValueError("Il mapping pazienti deve contenere identita canoniche non vuote")
        object.__setattr__(self, "graph_patients", MappingProxyType(mapping))
        if self.history is not None and not isinstance(self.history, ReleaseHistory):
            raise ValueError("history deve essere un ReleaseHistory")


def snapshot_digest(dataset):
    """Fingerprint del Dataset locale; nessun dato grezzo viene conservato."""
    digest = sha256()
    quads = sorted(tuple(term.n3() for term in quad) for quad in dataset.quads((None, None, None, None)))
    for quad in quads:
        for term in quad:
            data = term.encode("utf-8")
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


class ReleaseHistory:
    """Storico in memoria, serializzato da un lock per l'intero rilascio.

    Ambito dataset_id, condiviso anche tra principal diversi. Non e uno storage
    persistente: il servizio deve mantenerlo e non permetterne il reset ai client.
    """

    def __init__(self, *, max_records=1000):
        if type(max_records) is not int or max_records < 1:
            raise ValueError("max_records deve essere positivo")
        self._max_records = max_records
        self._records = {}
        self._snapshots = {}
        self._lock = RLock()

    @contextmanager
    def locked(self):
        with self._lock:
            yield

    def check_snapshot(self, dataset_id, fingerprint):
        with self._lock:
            previous = self._snapshots.get(dataset_id)
            if previous is not None and previous != fingerprint:
                raise ResultBlocked("Snapshot diverso da quello dei rilasci precedenti: risultato soppresso.")

    def record(self, *, dataset_id, fingerprint, query, cohorts, min_patients, check_queries, check_temporal):
        with self._lock:
            return self._record(dataset_id=dataset_id, fingerprint=fingerprint, query=query, cohorts=cohorts,
                                min_patients=min_patients, check_queries=check_queries, check_temporal=check_temporal)

    def _record(self, *, dataset_id, fingerprint, query, cohorts, min_patients, check_queries, check_temporal):
        if check_temporal:
            self.check_snapshot(dataset_id, fingerprint)
        digest = sha256(query.encode("utf-8")).hexdigest()
        candidate = tuple(frozenset(c) for c in cohorts)
        records = self._records.get(dataset_id, [])
        if check_queries:
            for old_digest, old_cohorts in records:
                if old_digest != digest and any(c and c == old for c in candidate for old in old_cohorts):
                    raise ResultBlocked("Storico: statistica diversa sulla stessa coorte, risultato soppresso.")
            # Raffina tutte le partizioni gia rilasciate, non solo confronti a coppie.
            sets = [c for _, groups in records for c in groups] + list(candidate)
            atoms = [set().union(set(), *sets)]
            for cohort in sets:
                atoms = [piece for atom in atoms for piece in (atom & cohort, atom - cohort) if piece]
            if any(len(atom) < min_patients for atom in atoms):
                raise ResultBlocked("Storico: differenza o intersezione troppo piccola, risultato soppresso.")
            item = (digest, candidate)
            if item not in records:
                if sum(len(items) for items in self._records.values()) >= self._max_records:
                    raise ResultBlocked("Capacita dello storico superata: risultato soppresso.")
                self._records.setdefault(dataset_id, []).append(item)
        if check_temporal:
            self._snapshots[dataset_id] = fingerprint


def preflight(dataset, policy, context):
    required = any(policy.enabled(name) for name in (
        "privacy_authorization", "privacy_distinct_persons", "privacy_query_history", "privacy_temporal_history"))
    if required and not isinstance(context, ExecutionContext):
        raise ResultBlocked("Le policy di privacy abilitate richiedono ExecutionContext fidato.")
    if policy.enabled("privacy_authorization"):
        for graph in dataset.contexts():
            if len(graph) and str(graph.identifier) not in context.allowed_graphs:
                raise ResultBlocked("Dataset fuori dal perimetro autorizzato per il principal.")
    if policy.enabled("privacy_distinct_persons") and not context.graph_patients:
        raise ResultBlocked("Manca il mapping fidato tra grafi e persone canoniche.")
    if any(policy.enabled(name) for name in ("privacy_query_history", "privacy_temporal_history")) and context.history is None:
        raise ResultBlocked("Manca lo storico condiviso dei rilasci.")
