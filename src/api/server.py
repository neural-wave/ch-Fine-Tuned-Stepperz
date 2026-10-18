"""HTTP translation/assessment contract; queries are never executed."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from agent_orchestration.local_models import CONFIG, open_models
from agent_orchestration.model_discovery import discover_served_model
from agent_orchestration.logging_setup import configure_logging
from .service import TranslationService

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 12000
WEB_DIR = Path(__file__).resolve().parent / "static"


class NlToSparqlRequest(BaseModel):
    text: str = Field(min_length=1, max_length=16384, strict=True)


class NlToSparqlResponse(BaseModel):
    sparql_query: str
    tokens_consumed: int = Field(ge=0)
    is_compliant: bool
    compliance_reason: str | None = None
    analytics: dict | None = None


class ErrorResponse(BaseModel):
    error: str


class StudyResponse(NlToSparqlResponse):
    analytics: dict


class StudyErrorResponse(ErrorResponse):
    analytics: dict
    sparql_query: str | None = None


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.log_path = configure_logging("sparql-api", console=True)
        logger.info("API logging file=%s", app.state.log_path)
        app.state.lock = asyncio.Lock()
        if service is not None:
            app.state.translator = service
            yield
        else:
            config = Path(os.getenv("NL2SPARQL_CONFIG", str(CONFIG))).resolve()
            settings = json.loads(config.read_text(encoding="utf-8-sig"))
            model_name = await discover_served_model(settings["base_url"], settings.get("model"))
            if model_name != settings.get("model"):
                logger.warning("Configured model=%s; using served model=%s from /models",
                               settings.get("model"), model_name)
            directory = CONFIG.parent
            schema = "SPHN clinical RDF. Retrieve class/property details from the schema MCP."
            policy = (directory / "policy.txt").read_text(encoding="utf-8-sig")
            permissions = (directory / "permissions.txt").read_text(encoding="utf-8-sig")
            async with open_models(config, assessment_mode=True, model_name=model_name) as (guard, generator):
                app.state.translator = TranslationService(guard, generator, schema=schema,
                    policy=policy, permissions=permissions)
                yield

    app = FastAPI(title="Natural Language to SPARQL API", version="1.0.0", lifespan=lifespan)
    app.mount("/ui", StaticFiles(directory=WEB_DIR), name="ui")

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(WEB_DIR / "index.html")

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        # Restore our handler if a later logging configuration detached/closed it.
        request.app.state.log_path = configure_logging("sparql-api", console=True)
        started = perf_counter()
        logger.info("HTTP request started method=%s path=%s", request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("HTTP request failed method=%s path=%s elapsed_seconds=%.3f",
                             request.method, request.url.path, perf_counter() - started)
            raise
        logger.info("HTTP request completed method=%s path=%s status=%s elapsed_seconds=%.3f",
                    request.method, request.url.path, response.status_code, perf_counter() - started)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(status_code=400, content={"error": "Expected JSON with 'text' as a non-empty string (maximum 16384 characters)."})

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse(status_code=error.status_code, content={"error": str(error.detail)})

    @app.exception_handler(Exception)
    async def unexpected(request, error):
        logger.exception("Unexpected API failure")
        return JSONResponse(status_code=500, content={"error": "Internal translation error."})

    async def run_translation(body, request, *, study=False):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "'text' must not be empty.")
        started = perf_counter()
        received_at = datetime.now(timezone.utc).isoformat()
        request_id = uuid4().hex
        queue_seconds = None
        queue_started = started

        def study_analytics(values):
            values = dict(values)
            values["timings"] = {**values.get("timings", {}),
                                 "queue": queue_seconds if queue_seconds is not None else perf_counter() - queue_started,
                                 "request_total": perf_counter() - started}
            values["request"] = {"id": request_id, "prompt": text, "received_at": received_at,
                                 "finished_at": datetime.now(timezone.utc).isoformat()}
            logger.info("Study execution request_id=%s queue_seconds=%.6f request_seconds=%.6f",
                        request_id, values["timings"]["queue"], values["timings"]["request_total"])
            return values

        def study_error(error, message, status):
            current, seen, values = error, set(), {"status": "error", "executed": False}
            query = None
            while current is not None and id(current) not in seen:
                seen.add(id(current))
                if hasattr(current, "execution_analytics"):
                    values = current.execution_analytics
                    query = getattr(current, "generated_query", None)
                    break
                current = current.__cause__ or current.__context__
            payload = {"error": message, "analytics": study_analytics(values)}
            if query is not None:
                payload["sparql_query"] = query
            return JSONResponse(status_code=status, content=payload)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                # Serialize access to the shared inference backend.
                queue_started = perf_counter()
                async with request.app.state.lock:
                    queue_seconds = perf_counter() - queue_started
                    result = dict(await request.app.state.translator.run(text))
                    if study:
                        result["analytics"] = study_analytics(result["analytics"])
                    elif request.headers.get("x-include-analytics") != "true":
                        result.pop("analytics", None)
                    return result
        except TimeoutError as error:
            logger.exception("Translation deadline exceeded")
            if study:
                return study_error(error, "Translation timed out.", 504)
            raise HTTPException(504, "Translation timed out.") from None
        except Exception as error:
            logger.exception("Model, retrieval or assessment failed (%s)", type(error).__name__)
            if study:
                return study_error(error, "Translation or assessment failed; inspect the server logs.", 502)
            raise HTTPException(502, "Translation or assessment failed; inspect the server logs.") from None

    @app.post("/nl-to-sparql", response_model=NlToSparqlResponse,
              response_model_exclude_none=True, operation_id="generateSparql",
              responses={"default": {"model": ErrorResponse},
                         **{code: {"model": ErrorResponse} for code in (400, 500, 502, 504)}})
    async def translate(body: NlToSparqlRequest, request: Request):
        return await run_translation(body, request)

    @app.post("/study/nl-to-sparql", response_model=StudyResponse,
              response_model_exclude_none=True, operation_id="studySparql",
              summary="Translate and return execution metrics and assessment metadata",
              responses={"default": {"model": ErrorResponse}, 400: {"model": ErrorResponse},
                         **{code: {"model": StudyErrorResponse} for code in (502, 504)}})
    async def study_translate(body: NlToSparqlRequest, request: Request):
        return await run_translation(body, request, study=True)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
