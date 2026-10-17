#!/usr/bin/env python3
"""
Esegue sul TUO Virtuoso le query di riferimento dei casi di test e salva i risultati attesi.

Per ogni caso compliant:
  - esegue la query di riferimento e salva il risultato in "expected_result"
  - segna lo stato: ok | vuoto (0 righe o solo zeri) | errore
  - (se esiste data/void_schema.json e sparql-llm e' installato) controlla che classi e
    proprieta' usate esistano nei vostri dati, e lo scrive in "void_issues"
I casi non compliant vengono copiati cosi' come sono (non hanno query di riferimento).

Uso (dalla cartella hackathon-virtuoso-release, Virtuoso acceso):
  python src/run_references.py                                   # benchmark/testcases.jsonl
  python src/run_references.py --in benchmark/testcases.jsonl

Produce:
  benchmark/testcases_checked.jsonl  tutti i casi, con risultati e stato (da rileggere)
  benchmark/testcases_final.jsonl    solo i casi utilizzabili (stato ok + non compliant),
                                     pronti per:  python src/benchmark.py --questions benchmark/testcases_final.jsonl
"""
import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests


def run_sparql(endpoint, query, timeout):
    t = time.perf_counter()
    r = requests.post(endpoint, data={"query": query},
                      headers={"Accept": "application/sparql-results+json"}, timeout=timeout)
    elapsed = time.perf_counter() - t
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}: {r.text[:400]}")
    data = r.json()
    if "boolean" in data:
        return [{"result": data["boolean"]}], elapsed
    return [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]], elapsed


def is_empty(rows):
    if not rows:
        return True
    values = [v for r in rows for v in r.values()]
    return all(str(v) in ("0", "0.0", "") for v in values)


def make_void_checker(void_json):
    """Restituisce una funzione query -> lista di problemi, oppure None se non disponibile."""
    if not Path(void_json).exists():
        return None
    os.environ.setdefault("SETTINGS_FILEPATH", str(Path(tempfile.gettempdir()) / "sparql_llm_settings.json"))
    Path(os.environ["SETTINGS_FILEPATH"]).write_text(json.dumps({"endpoints": []}))
    Path("data").mkdir(exist_ok=True)
    try:
        from sparql_llm import validate_sparql_with_void
        from sparql_llm.utils import get_prefix_converter
    except Exception as e:  # noqa: BLE001
        print(f"(controllo sul VoID saltato: sparql-llm non disponibile: {e})")
        return None
    void = json.loads(Path(void_json).read_text())
    conv = get_prefix_converter({"sphn": "https://biomedit.ch/rdf/sphn-schema/sphn#"})

    class Same(dict):
        def __contains__(self, k):
            return True

        def __getitem__(self, k):
            return void

    def check(query):
        q = re.sub(r"(?im)^\s*DEFINE\s+.*$", "", query)
        q = re.sub(r'OPTION\s*\(\s*inference\s*"[^"]*"\s*\)', "", q, flags=re.I)
        issues = validate_sparql_with_void(q, "http://local-void", prefix_converter=conv,
                                           endpoints_void_dict=Same())
        # i codici delle terminologie nel VoID sono raggruppati: ignora i "type does not exist" su di essi
        return sorted(i for i in issues if not ("does not exist" in i and "sphn:" not in i.split("does not exist")[0]))
    return check


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="benchmark/testcases.jsonl")
    ap.add_argument("--sparql", default="http://localhost:8890/sparql")
    ap.add_argument("--void-json", default="data/void_schema.json")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    cases = [json.loads(l) for l in Path(args.inp).read_text().splitlines() if l.strip()]
    check_void = make_void_checker(args.void_json)
    out_dir = Path(args.inp).parent

    counts = {"ok": 0, "vuoto": 0, "errore": 0}
    print(f"{'id':<6}{'stato':<9}{'righe':>6}{'tempo s':>9}  domanda")
    for c in cases:
        if not c.get("reference"):
            c["status"] = "non_compliant"
            continue
        if check_void:
            c["void_issues"] = check_void(c["reference"])
        try:
            rows, t = run_sparql(args.sparql, c["reference"], args.timeout)
            c["expected_result"] = rows[:200]
            c["reference_seconds"] = round(t, 3)
            c["status"] = "vuoto" if is_empty(rows) else "ok"
            n = len(rows)
        except Exception as e:  # noqa: BLE001
            c["status"], c["error"], n, t = "errore", str(e)[:400], 0, 0.0
        counts[c["status"]] += 1
        flag = " (VoID: " + str(len(c["void_issues"])) + " problemi)" if c.get("void_issues") else ""
        print(f"{c['id']:<6}{c['status']:<9}{n:>6}{t:>9.3f}  {c['question'][:60]}{flag}")

    checked = out_dir / "testcases_checked.jsonl"
    final = out_dir / "testcases_final.jsonl"
    with open(checked, "w") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    usable = [c for c in cases if c["status"] in ("ok", "non_compliant")]
    with open(final, "w") as f:
        for c in usable:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_nc = sum(c["status"] == "non_compliant" for c in cases)
    print("\n" + "=" * 70)
    print(f"Query di riferimento: {counts['ok']} ok, {counts['vuoto']} vuote, {counts['errore']} in errore")
    print(f"Casi non compliant (nessuna query da eseguire): {n_nc}")
    print(f"Tutti i casi con risultati: {checked}")
    print(f"Casi pronti per il benchmark ({len(usable)}): {final}")
    if counts["vuoto"] or counts["errore"]:
        print("\nCasi vuoti o in errore: probabilmente quel codice o quella proprieta' non c'e'")
        print("nei vostri dati. Guardate 'error' e 'void_issues' in testcases_checked.jsonl:")
        print("correggete la query (o cambiate il codice) oppure lasciate il caso fuori.")


if __name__ == "__main__":
    main()
