"""POST /nl-to-sparql — generatore (LLM_ENGINE/sparql_agent) + verifica statica (sparql_analyzer).

Contratto: docs/specifications/API_specification.md
  request : {"text": "..."}
  200     : {"sparql_query", "tokens_consumed", "is_compliant", ["compliance_reason" solo se false]}
  errori  : {"error": "..."}   400 input non valido · 502 modello/MCP irraggiungibili

Il file va nella ROOT del repo. Si avvia con l'ambiente di LLM_ENGINE (vedi README nella risposta):
  cd LLM_ENGINE && uv add fastapi uvicorn pyshacl==0.25.0 pyparsing==3.2.1 && cd ..
  uv run --project LLM_ENGINE uvicorn server:app --port 8000

Variabili d'ambiente opzionali:
  NL2SPARQL_MODE          deterministic (default, 1 retrieval + 1 chiamata LLM) | autonomous
  NL2SPARQL_BACKEND       sphn-void (default) | public
  NL2SPARQL_MAX_ATTEMPTS  generazioni massime per richiesta (default 2)
  NL2SPARQL_POLICY        policy del checker (default config/policies/default.json)
  NL2SPARQL_ENV           file .env dell'agente (default LLM_ENGINE/.env)
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

# --- rende importabili sparql_analyzer (src/) e sparql_agent (LLM_ENGINE/src/)
ROOT = Path(__file__).resolve().parent
for _path in (ROOT / "src", ROOT / "LLM_ENGINE" / "src"):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

MAX_ATTEMPTS = int(os.getenv("NL2SPARQL_MAX_ATTEMPTS", "2"))
AGENT_MODE = os.getenv("NL2SPARQL_MODE", "deterministic")
RETRIEVAL_BACKEND = os.getenv("NL2SPARQL_BACKEND", "sphn-void")
POLICY_FILE = Path(os.getenv("NL2SPARQL_POLICY", str(ROOT / "config" / "policies" / "default.json")))
ENV_FILE = Path(os.getenv("NL2SPARQL_ENV", str(ROOT / "LLM_ENGINE" / ".env")))

# Stati di run_question che indicano un guasto dell'infrastruttura, non della traduzione.
INFRA_STATUSES = {"connection_error", "client_error", "llm_error", "missing_tools", "retrieval_failed"}

# Aggiunto al SYSTEM_PROMPT dell'agente (non alla domanda, che serve pulita al retrieval).
SPHN_HINT = """
SPHN rules (the target is SPHN clinical data in Virtuoso):
- Each patient's data lives in its own named graph: match clinical data inside GRAPH ?g { ... }.
- To count patients, count distinct graphs, e.g.
  SELECT (COUNT(?pseudo_id) AS ?countResult) WHERE { { SELECT DISTINCT(?g AS ?pseudo_id) WHERE { GRAPH ?g { ... } } } }
- Write standard SPARQL only: no DEFINE and no OPTION(...) clauses.
- Translate the request faithfully. Never change its meaning to make it look acceptable:
  if it asks for identifiers or individual records, write the query that returns them.
"""


# ---------------------------------------------------------------- tipi interni
@dataclass
class Generation:
    sparql: str = ""
    tokens: int = 0
    problem: str | None = None      # perché non c'è una query utilizzabile
    infra_error: bool = False       # modello/MCP irraggiungibili: inutile riprovare


@dataclass
class Verdict:
    compliant: bool
    reasons: list[str] = field(default_factory=list)
    retryable: bool = False         # solo errori tecnici (sintassi), mai violazioni di privacy


class TranslationError(Exception):
    """Modello o retrieval non raggiungibili."""


# ---------------------------------------------------------------- generazione
_ENDPOINT_LINE = re.compile(r"^\s*#\+?\s*endpoint:.*$\n?", re.MULTILINE | re.IGNORECASE)


@lru_cache(maxsize=1)
def _agent_config():
    from sparql_agent import agent as agent_module
    from sparql_agent.config import Config
    from sparql_agent.mcp_client import select_retrieval_backend

    if SPHN_HINT not in agent_module.SYSTEM_PROMPT:
        agent_module.SYSTEM_PROMPT += SPHN_HINT
    config = Config.from_env(ENV_FILE)
    return select_retrieval_backend(config, RETRIEVAL_BACKEND or None)


async def generate_sparql(question: str, feedback: list[str] | None = None) -> Generation:
    from sparql_agent.agent import run_question

    prompt = question
    if feedback:
        prompt += ("\n\nYour previous query could not be used: " + "; ".join(feedback)
                   + " Fix only these technical problems; keep the meaning of the request.")
    result = await run_question(_agent_config(), prompt, mode=AGENT_MODE)
    tokens = result.total_tokens or 0
    if result.status in INFRA_STATUSES:
        return Generation(tokens=tokens, infra_error=True,
                          problem=f"{result.status}: {'; '.join(result.errors[-2:])}")
    query = _ENDPOINT_LINE.sub("", result.generated_query or "").strip()
    if not query:
        return Generation(tokens=tokens, problem=(result.errors[-1] if result.errors else result.status))
    return Generation(sparql=query, tokens=tokens)


# ---------------------------------------------------------------- compliance
# Estensioni Virtuoso ammesse dalla spec: solo queste due forme esatte vengono tolte prima
# del controllo statico (che usa rdflib e non le conosce). Qualsiasi altro DEFINE/OPTION
# viene rifiutato: alcuni DEFINE cambiano grafi e comportamento del motore.
_ALLOWED_DEFINE = re.compile(r'^\s*DEFINE\s+sql:select-option\s+"order"\s*$', re.IGNORECASE)
_ANY_DEFINE = re.compile(r"^\s*DEFINE\b", re.IGNORECASE)
_ALLOWED_OPTION = re.compile(
    r'OPTION\s*\(\s*inference\s+"https://biomedit\.ch/rdf/sphn-resource/global"\s*\)', re.IGNORECASE)
_ANY_OPTION = re.compile(r"\bOPTION\s*\(", re.IGNORECASE)


def split_virtuoso_extensions(query: str) -> tuple[str, list[str]]:
    problems, lines = [], []
    for line in query.splitlines():
        if _ALLOWED_DEFINE.match(line):
            continue
        if _ANY_DEFINE.match(line):
            problems.append(f"The Virtuoso directive '{line.strip()}' is not allowed.")
            continue
        lines.append(line)
    clean = _ALLOWED_OPTION.sub("", "\n".join(lines))
    if _ANY_OPTION.search(clean):
        problems.append("Only OPTION(inference \"https://biomedit.ch/rdf/sphn-resource/global\") is allowed.")
    return clean, problems


# Spiegazioni per i codici del validatore. R2 è dedotto dai casi di test: verificare.
RULE_TEXT = {
    "R1": "The query targets a single, identifiable patient (a fixed patient graph, identifier or filter).",
    "R2": "The query does not return aggregated information across all patients.",
    "R3": "The query matches the graph without restriction (a triple pattern made only of variables).",
    "R4": "Only read-only aggregate SELECT queries are allowed; updates, ASK, CONSTRUCT and DESCRIBE are rejected.",
    "R5": "The query exposes patient identifiers or individual resources in its output.",
    "SYNTAX": "The query is not valid SPARQL.",
}


@lru_cache(maxsize=1)
def _validate_kwargs() -> dict:
    from sparql_analyzer.compliance import validate
    from sparql_analyzer.configuration.policy import Policy

    if "policy" not in inspect.signature(validate).parameters:
        return {}  # validate usa la policy predefinita, identica a default.json
    return {"policy": Policy.from_dict(json.loads(POLICY_FILE.read_text(encoding="utf-8")))}


def _reasons(result: dict) -> list[str]:
    reasons: list[str] = []
    for finding in result.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        text = next((finding[k] for k in ("message", "description", "detail", "reason")
                     if isinstance(finding.get(k), str) and finding[k].strip()), None)
        text = text or RULE_TEXT.get(finding.get("code", ""))
        if text and text not in reasons:
            reasons.append(text)
    for code in result.get("violations") or []:
        text = RULE_TEXT.get(code, f"Violated rule {code}.")
        if text not in reasons:
            reasons.append(text)
    return reasons or ["The query violates the compliance policy."]


def check_compliance(sparql: str) -> Verdict:
    clean, problems = split_virtuoso_extensions(sparql)
    if problems:
        return Verdict(False, problems)
    from sparql_analyzer.compliance import validate

    result = validate(clean, **_validate_kwargs())
    if result.get("is_compliant") is True:
        return Verdict(True)
    codes = {f.get("code") for f in result.get("findings") or [] if isinstance(f, dict)}
    return Verdict(False, _reasons(result), retryable="SYNTAX" in codes)


# ------------------------------------------------------------------ API
class NlToSparqlRequest(BaseModel):
    text: str = Field(..., min_length=1)


class NlToSparqlResponse(BaseModel):
    sparql_query: str
    tokens_consumed: int
    is_compliant: bool
    compliance_reason: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Carica config e policy all'avvio: errori di configurazione emergono subito,
    # e la prima richiesta non paga il costo degli import.
    if os.getenv("NL2SPARQL_SKIP_WARMUP") != "1":
        _agent_config()
        _validate_kwargs()
    yield


app = FastAPI(title="Natural Language to SPARQL API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    if any(e.get("loc", [None])[-1] == "text" for e in exc.errors()):
        msg = "'text' must be a non-empty string."
    else:
        msg = "Request body must be JSON of the form {\"text\": \"...\"}."
    return JSONResponse(status_code=400, content={"error": msg})


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(TranslationError)
async def _translation_error(_: Request, exc: TranslationError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"error": str(exc)})


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": f"Internal error: {type(exc).__name__}: {exc}"})


def _response(query: str, tokens: int, verdict: Verdict) -> NlToSparqlResponse:
    if verdict.compliant:
        return NlToSparqlResponse(sparql_query=query, tokens_consumed=tokens, is_compliant=True)
    reason = " ".join(r if r.endswith(".") else r + "." for r in verdict.reasons)
    return NlToSparqlResponse(sparql_query=query, tokens_consumed=tokens,
                              is_compliant=False, compliance_reason=reason)


@app.post("/nl-to-sparql", response_model=NlToSparqlResponse,
          response_model_exclude_none=True, operation_id="generateSparql")
async def nl_to_sparql(body: NlToSparqlRequest):
    question = body.text.strip()
    if not question:
        return JSONResponse(status_code=400, content={"error": "'text' must not be empty."})

    tokens = 0
    feedback: list[str] | None = None
    best: tuple[str, Verdict] | None = None
    problem = None

    for _ in range(max(1, MAX_ATTEMPTS)):
        gen = await generate_sparql(question, feedback)
        tokens += gen.tokens
        if gen.infra_error:
            raise TranslationError(f"Translation failed: {gen.problem}")
        if not gen.sparql:
            problem = gen.problem
            feedback = [f"no usable query was produced ({gen.problem})"]
            continue
        verdict = await asyncio.to_thread(check_compliance, gen.sparql)
        best = (gen.sparql, verdict)
        # Si riprova SOLO per errori tecnici. Una violazione di privacy è il verdetto
        # corretto per la richiesta: "aggiustarla" trasformerebbe una richiesta
        # non conforme in una risposta conforme, cioè un errore di valutazione.
        if verdict.compliant or not verdict.retryable:
            break
        feedback = verdict.reasons

    if best is None:
        return _response("", tokens, Verdict(False, [f"No SPARQL query could be generated ({problem})"]))
    return _response(best[0], tokens, best[1])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}