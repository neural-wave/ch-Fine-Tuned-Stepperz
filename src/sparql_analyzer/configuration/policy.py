"""Configurazione immutabile per richiesta: nessun interruttore globale."""

from dataclasses import dataclass, field, replace
from types import MappingProxyType


@dataclass(frozen=True)
class Check:
    description: str
    requires: tuple[str, ...] = ()
    default_enabled: bool = True


_checks = {
    "syntax_analysis": Check("Analisi dell'AST sintattico; il parsing rimane necessario."),
    "algebra_analysis": Check("Analisi dell'algebra SPARQL."),
    "scope_analysis": Check("Isolamento delle variabili locali delle sottoquery."),
    "sensitivity_analysis": Check("Propagazione della sensibilita attraverso alias e aggregati.", ("algebra_analysis", "scope_analysis")),
    "numeric_analysis": Check("Classificazione delle misure e delle espressioni numeriche.", ("algebra_analysis", "scope_analysis")),
    "aggregate_analysis": Check("Propagazione delle dipendenze da aggregati.", ("algebra_analysis", "scope_analysis")),
    "support_analysis": Check("Valutazione delle righe di supporto e provenienza.", ("algebra_analysis", "scope_analysis")),
    "control_analysis": Check("Provenienza delle condizioni nel percorso annidato.", ("support_analysis",)),
    "query_length": Check("Lunghezza massima della query."),
}

for name, description in {
    "select_only": "Ammette soltanto SELECT.",
    "known_nodes": "Rifiuta operatori dell'algebra non verificati.",
    "fixed_graph": "Rifiuta grafi costanti non autorizzati.",
    "patient_reference": "Rifiuta URI espliciti nel namespace pazienti.",
    "clinical_pattern": "Richiede almeno un pattern clinico.",
    "unrestricted_triple": "Rifiuta triple con tre variabili.",
    "fixed_subject": "Rifiuta soggetti URI costanti.",
    "constant_identifier": "Rifiuta identificatori costanti.",
    "predicate_shape": "Rifiuta predicati variabili e property path.",
    "predicate_vocabulary": "Limita il vocabolario dei predicati.",
    "values": "Rifiuta VALUES non verificati.",
    "category_group": "Rifiuta raggruppamenti esterni per categoria.",
    "supported_aggregates": "Limita gli aggregati staticamente verificati.",
}.items():
    _checks[name] = Check(description, ("algebra_analysis",))

for name, description in {
    "sensitive_filter": "Rifiuta filtri su risorse e identificatori individuali.",
    "sensitive_bind": "Rifiuta costanti assegnate a variabili sensibili.",
    "individual_group": "Rifiuta raggruppamenti individuali nell'output esterno.",
    "sensitive_count": "Rifiuta espressioni COUNT dipendenti da identificatori.",
    "sensitive_output": "Rifiuta risorse e identificatori nell'output.",
}.items():
    _checks[name] = Check(description, ("sensitivity_analysis",))

_checks["numeric_aggregates"] = Check("SUM/AVG soltanto su misure autorizzate.", ("numeric_analysis",))
_checks["aggregate_output"] = Check("Output composto esclusivamente da aggregati.", ("aggregate_analysis",))

OPERATOR_CHECKS = {
    operator: "forbid_" + operator.lower().replace(" ", "_")
    for operator in ("GROUP_CONCAT", "SAMPLE", "MIN", "MAX", "SERVICE", "ASK",
                     "CONSTRUCT", "DESCRIBE", "FROM", "FROM NAMED", "SPARQL UPDATE",
                     "LOAD", "CLEAR", "DROP", "CREATE", "ADD", "MOVE", "COPY", "INSERT", "DELETE")
}
for operator, name in OPERATOR_CHECKS.items():
    _checks[name] = Check(f"Vieta esplicitamente {operator}.", ("syntax_analysis",))

for name, description in {
    "runtime_graph_scope": "Verifica il namespace dei grafi durante l'esecuzione.",
    "runtime_cohort": "Soglia minima sui grafi contribuenti.",
    "runtime_work_limit": "Limite delle righe di supporto/intermedie.",
    "runtime_measures": "Controlla datatype e valori delle misure intermedie.",
    "runtime_aggregates": "Limita gli aggregati eseguibili dal percorso verificato.",
    "runtime_expressions": "Limita gli argomenti e le proiezioni numeriche verificate.",
    "runtime_distinct_star": "Rifiuta COUNT(DISTINCT *).",
    "runtime_single_graph": "Richiede una variabile grafo nel percorso semplice.",
    "runtime_global_group": "Richiede una sola riga aggregata finale.",
}.items():
    _checks[name] = Check(description, ("support_analysis",))
_checks["runtime_control_cohort"] = Check("Soglia sulle dipendenze di controllo annidate.", ("control_analysis",))
_checks["result_shape"] = Check("Struttura dei contenitori SPARQL Results JSON.")
_checks["result_columns"] = Check("Colonne esattamente uguali a quelle approvate.", ("result_shape",))
_checks["result_single_row"] = Check("Una sola riga nella risposta finale.", ("result_shape",))
_checks["result_metadata"] = Check("Nessun campo o metadato aggiuntivo.", ("result_shape",))
_checks["result_numbers"] = Check("Output composto da letterali numerici verificati.")
_checks["numeric_format"] = Check("Forma lessicale coerente con il datatype numerico.")
_checks["count_format"] = Check("Conteggi interi non negativi.", ("result_numbers", "aggregate_analysis"))
_checks["finite_numbers"] = Check("Rifiuta numeri non finiti.")
_checks["numeric_bounds"] = Check("Limiti su lunghezza ed esponente dei numeri.")
_checks["result_consistency"] = Check("Confronta la risposta con gli aggregati ricalcolati.", ("support_analysis", "result_numbers"))
_checks["runtime_expressions"] = Check(_checks["runtime_expressions"].description, ("support_analysis", "numeric_analysis", "aggregate_analysis"))
_checks["category_group"] = Check(_checks["category_group"].description, ("sensitivity_analysis",))

# Nuove protezioni opt-in: alcune richiedono un contesto fornito dal servizio.
for name, description, requires in (
    ("privacy_effective_contributors", "Coorti dei contributi effettivi: segue IF/COALESCE e riempimenti artificiali.", ("runtime_cohort",)),
    ("privacy_correlated_patterns", "Rifiuta pattern clinici nel default graph, non correlati a GRAPH.", ("algebra_analysis",)),
    ("privacy_distinct_persons", "Conta persone canoniche dal mapping fidato, non grafi distinti.", ("runtime_cohort",)),
    ("privacy_authorization", "Verifica principal e ACL del dataset prima di interrogare i dati.", ()),
    ("privacy_query_history", "Blocca differencing, piccoli complementi e statistiche diverse sulla stessa coorte.", ("privacy_distinct_persons", "runtime_control_cohort")),
    ("privacy_temporal_history", "Vincola i rilasci allo stesso snapshot del dataset.", ("support_analysis",)),
    ("privacy_normalize_errors", "Sostituisce errori imprevisti con un errore pubblico privo di dati.", ()),
):
    _checks[name] = Check(description, requires, default_enabled=False)

_checks["adequacy_shacl"] = Check("Valida separatamente i grafi RDF con SHACL Core e SHACL-SPARQL prima del rilascio.", default_enabled=False)
for name, description in {
    "adequacy_targets": "Richiede almeno un focus node effettivo per ogni grafo dati non vuoto.",
    "adequacy_meta_shapes": "Verifica le shape con il meta-schema SHACL prima di validare i dati.",
    "adequacy_warnings": "Considera bloccanti anche i risultati SHACL Warning.",
    "adequacy_infos": "Considera bloccanti anche i risultati SHACL Info.",
}.items():
    _checks[name] = Check(description, ("adequacy_shacl",), default_enabled=False)

CHECKS = MappingProxyType(_checks)


@dataclass(frozen=True)
class Policy:
    """Usare with_checks per cambiare interruttori e gestire le dipendenze.

    Disattivare un'analisi disattiva anche i controlli che la richiedono.
    Attivare un controllo attiva le analisi necessarie. La configurazione
    effettiva e sempre esportabile con to_dict().
    """

    enabled_checks: frozenset[str] = field(default_factory=lambda: frozenset(name for name, check in CHECKS.items() if check.default_enabled))
    max_query_chars: int = 100_000
    min_patients: int = 5
    max_support_rows: int = 100_000
    max_numeric_chars: int = 128
    max_numeric_exponent: int = 1000

    def __post_init__(self):
        object.__setattr__(self, "enabled_checks", frozenset(self.enabled_checks))
        unknown = self.enabled_checks - CHECKS.keys()
        if unknown:
            raise ValueError(f"Controlli sconosciuti: {sorted(unknown)}")
        for name in self.enabled_checks:
            if not set(CHECKS[name].requires) <= self.enabled_checks:
                raise ValueError(f"Dipendenze mancanti per {name}: {CHECKS[name].requires}")
        for name in ("max_query_chars", "max_support_rows", "max_numeric_chars", "max_numeric_exponent", "min_patients"):
            value = getattr(self, name)
            if type(value) is not int or value < (2 if name == "min_patients" else 1):
                raise ValueError(f"Limite non valido: {name}")

    def enabled(self, name):
        if name not in CHECKS:
            raise ValueError(f"Controllo sconosciuto: {name}")
        return name in self.enabled_checks

    @classmethod
    def hardened(cls):
        """Abilita tutti i controlli; richiede contesti privacy e SHACL fidati."""
        return cls(enabled_checks=frozenset(CHECKS))

    @classmethod
    def adequacy(cls):
        """Controlli predefiniti e tutte le opzioni di adeguatezza SHACL."""
        return cls().with_checks(**{name: True for name in CHECKS if name.startswith("adequacy_")})

    def with_checks(self, **changes):
        if changes.keys() - CHECKS.keys():
            raise ValueError(f"Controlli sconosciuti: {sorted(changes.keys() - CHECKS.keys())}")
        if any(type(value) is not bool for value in changes.values()):
            raise ValueError("Gli interruttori devono essere booleani")
        enabled = set(self.enabled_checks)
        disabled = {name for name, value in changes.items() if not value}
        enabled.difference_update(disabled)
        while True:
            removed = {name for name in enabled if not set(CHECKS[name].requires) <= enabled}
            if not removed:
                break
            enabled.difference_update(removed)

        def enable(name):
            if name in disabled:
                raise ValueError(f"Configurazione contraddittoria: {name} e richiesto ma disattivato")
            for dependency in CHECKS[name].requires:
                enable(dependency)
            enabled.add(name)

        for name, value in changes.items():
            if value:
                enable(name)
        return replace(self, enabled_checks=frozenset(enabled))

    def to_dict(self):
        return {"checks": {name: self.enabled(name) for name in CHECKS},
                "limits": {name: getattr(self, name) for name in (
                    "max_query_chars", "min_patients", "max_support_rows",
                    "max_numeric_chars", "max_numeric_exponent")}}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.keys() - {"checks", "limits"}:
            raise ValueError("Configurazione attesa: checks e limits")
        checks, limits = value.get("checks", {}), value.get("limits", {})
        if not isinstance(checks, dict) or not isinstance(limits, dict):
            raise ValueError("checks e limits devono essere oggetti JSON")
        allowed = cls().to_dict()["limits"]
        if limits.keys() - allowed.keys():
            raise ValueError(f"Limiti sconosciuti: {sorted(limits.keys() - allowed.keys())}")
        return replace(cls().with_checks(**checks), **limits)


DEFAULT_POLICY = Policy()
