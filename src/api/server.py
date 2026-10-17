"""HTTP translation/assessment contract; queries are never executed."""
import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from agent_orchestration.local_models import CONFIG, open_models
from agent_orchestration.logging_setup import configure_logging
from .service import TranslationService

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 120


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


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        configure_logging("sparql-api")
        app.state.lock = asyncio.Lock()
        if service is not None:
            app.state.translator = service
            yield
        else:
            config = Path(os.getenv("NL2SPARQL_CONFIG", str(CONFIG))).resolve()
            directory = CONFIG.parent
            schema = "SPHN clinical RDF. Retrieve class/property details from the schema MCP."
            policy = (directory / "policy.txt").read_text(encoding="utf-8-sig")
            permissions = (directory / "permissions.txt").read_text(encoding="utf-8-sig")
            async with open_models(config, assessment_mode=True) as (guard, generator):
                app.state.translator = TranslationService(guard, generator, schema=schema,
                    policy=policy, permissions=permissions)
                yield

    app = FastAPI(title="Natural Language to SPARQL API", version="1.0.0", lifespan=lifespan)

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

    @app.post("/nl-to-sparql", response_model=NlToSparqlResponse,
              response_model_exclude_none=True, operation_id="generateSparql",
              responses={"default": {"model": ErrorResponse},
                         **{code: {"model": ErrorResponse} for code in (400, 500, 502, 504)}})
    async def translate(body: NlToSparqlRequest, request: Request):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "'text' must not be empty.")
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                # Serialize access to the shared inference backend.
                async with request.app.state.lock:
                    result = await request.app.state.translator.run(text)
                    if request.headers.get("x-include-analytics") != "true":
                        result.pop("analytics", None)
                    return result
        except TimeoutError:
            logger.exception("Translation deadline exceeded")
            raise HTTPException(504, "Translation timed out.") from None
        except Exception:
            logger.exception("Model, retrieval or assessment failed")
            raise HTTPException(502, "Translation or assessment failed; inspect the server logs.") from None

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
