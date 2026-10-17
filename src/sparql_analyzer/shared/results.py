"""Contratto di restituzione e controlli numerici condivisi."""

import re
from decimal import Decimal, InvalidOperation
from sparql_analyzer.shared.algebra import nodes
from sparql_analyzer.shared.expressions import NUMERIC_TYPES
from sparql_analyzer.configuration.policy import DEFAULT_POLICY

class ResultBlocked(ValueError):
    """Errore pubblico privo dei dati contenuti nel risultato bloccato."""


class UnsupportedExecution(ResultBlocked):
    """Limite del valutatore, distinto da una restrizione configurabile."""


def number(cell, *, count=False, policy=DEFAULT_POLICY):
    try:
        if (not isinstance(cell, dict) or
                (policy.enabled("result_metadata") and set(cell) != {"type", "datatype", "value"}) or
                cell["type"] != "literal" or cell["datatype"] not in NUMERIC_TYPES or
                not isinstance(cell["value"], str) or
                (policy.enabled("numeric_bounds") and len(cell["value"]) > policy.max_numeric_chars)):
            raise ResultBlocked("Valore incompatibile con una statistica numerica approvata.")
        if count and policy.enabled("count_format") and (cell["datatype"] != "http://www.w3.org/2001/XMLSchema#integer" or
                      not re.fullmatch(r"[0-9]{1,20}", cell["value"])):
            raise ResultBlocked("Valore incompatibile con un conteggio intero approvato.")
        datatype = cell["datatype"].rsplit("#", 1)[-1]
        if policy.enabled("numeric_format") and datatype not in {"decimal", "float", "double"} and not re.fullmatch(r"[+-]?[0-9]+", cell["value"]):
            raise ResultBlocked("Formato incompatibile con il datatype intero.")
        if policy.enabled("numeric_format") and datatype == "decimal" and not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", cell["value"]):
            raise ResultBlocked("Formato incompatibile con il datatype decimale.")
        value = Decimal(cell["value"])
        if ((policy.enabled("finite_numbers") and not value.is_finite()) or
                (policy.enabled("numeric_bounds") and value.is_finite() and abs(value.adjusted()) > policy.max_numeric_exponent)):
            raise ResultBlocked("Statistica non finita o fuori dai limiti numerici.")
        return value
    except (InvalidOperation, ValueError, TypeError, KeyError) as error:
        if isinstance(error, ResultBlocked):
            raise
        raise ResultBlocked("Valore numerico non valido.") from error


def check_payload(payload, columns, *, numeric_columns=(), policy=DEFAULT_POLICY):
    """Valida uno SPARQL Results JSON rispetto alle colonne COUNT approvate.

    Non autorizza da solo la risposta: non verifica provenienza o coorte.
    """
    if not any(policy.enabled(name) for name in ("result_shape", "result_numbers")):
        return
    try:
        if policy.enabled("result_numbers") and (
                not isinstance(payload, dict) or not isinstance(payload.get("results"), dict) or
                not isinstance(payload["results"].get("bindings"), list)):
            raise ResultBlocked("Attesa una risposta con statistiche numeriche.")
        if policy.enabled("result_shape") and (
                not isinstance(payload, dict) or not isinstance(payload.get("head"), dict) or
                not isinstance(payload.get("results"), dict) or
                not isinstance(payload["head"].get("vars"), list) or
                "bindings" not in payload["results"]):
            raise ResultBlocked("Struttura della risposta inattesa.")
        if policy.enabled("result_metadata") and set(payload) != {"head", "results"}:
            raise ResultBlocked("Struttura della risposta inattesa.")
        if policy.enabled("result_metadata") and set(payload["head"]) != {"vars"}:
            raise ResultBlocked("Metadati delle colonne inattesi.")
        if policy.enabled("result_columns") and payload["head"]["vars"] != columns:
            raise ResultBlocked("Colonne della risposta diverse da quelle approvate.")
        if policy.enabled("result_metadata") and set(payload["results"]) != {"bindings"}:
            raise ResultBlocked("Struttura dei risultati inattesa.")
        rows = payload.get("results", {}).get("bindings", [])
        if policy.enabled("result_shape") and (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)):
            raise ResultBlocked("Struttura dei risultati inattesa.")
        if policy.enabled("result_single_row") and len(rows) != 1:
            raise ResultBlocked("Attesa una sola riga di conteggi globali.")
        for row in rows:
            if policy.enabled("result_columns") and set(row) != set(columns):
                raise ResultBlocked("Colonne mancanti o aggiuntive nella riga.")
            if policy.enabled("result_numbers"):
                for column, cell in row.items():
                    number(cell, count=column not in numeric_columns, policy=policy)
    except (KeyError, TypeError, AttributeError) as error:
        raise ResultBlocked("Risposta malformata.") from error


