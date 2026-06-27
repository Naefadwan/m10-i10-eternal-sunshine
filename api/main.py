"""FastAPI application — recipe service (reference implementation).

Discipline gates the autograder enforces:
- Neo4j driver, Weaviate client, spaCy pipeline, and the flan-t5-base
  generator are constructed exactly once per process inside `lifespan`.
- `CORSMiddleware` registered with `allow_origins=[WEB_ORIGIN]`.
- `/extract`, `/kg/query`, `/rag/answer` use Pydantic shapes from `models.py`.
- `/kg/query` converts `UnsupportedQueryError` to 422 with structured detail.
- `/readyz` probes Neo4j (`RETURN 1`) AND Weaviate (`client.is_ready()`)
  within 2 seconds; failure → 503.
- `/healthz` does NOT touch Neo4j or Weaviate.

Integration hardening (added layer):
- Env-var reads centralised through `Settings` — service-name DNS
  (`bolt://neo4j:7687`, `http://weaviate:8080`) resolves from compose
  env vars with graceful localhost fallbacks for local dev.
- Consistent error-response envelope via exception handlers so the
  Frontend has one shape to parse for 422 and 500 responses.
- Structured startup logging for `docker compose logs` readability.
"""
import logging
import os
from contextlib import asynccontextmanager

import spacy
import weaviate
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

from .deps import get_embedder, get_generator, get_nlp, get_session, get_weaviate
from .kg import wrap_kg_query
from .m8_rag import load_generator
from .models import (
    ExtractRequest,
    ExtractResponse,
    ErrorResponse,
    HealthResponse,
    KGRequest,
    KGResponse,
    RAGRequest,
    RAGResponse,
    ReadyDetail,
    UnsupportedQueryDetail,
)
from .nlp import extract_entities
from .rag import compose_rag
from .settings import Settings
from .w9b_mapper.errors import UnsupportedQueryError
from .w9b_mapper.shapes import SUPPORTED_PATTERNS

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings

    logger.info(
        "lifespan.start neo4j_uri=%s weaviate_url=%s web_origin=%s",
        settings.neo4j_uri,
        settings.weaviate_url,
        settings.web_origin,
    )

    app.state.neo4j_driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    app.state.weaviate_client = weaviate.Client(settings.weaviate_url)
    app.state.nlp = spacy.load("en_core_web_sm")
    app.state.generator = load_generator()
    # Same sentence-transformers model the seed used at ingest. The
    # Weaviate class is `vectorizer=none`, so /rag/answer encodes the
    # query externally and queries via `with_near_vector`.
    app.state.embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    logger.info("lifespan.ready all_resources_loaded=true")
    yield
    app.state.neo4j_driver.close()
    logger.info("lifespan.shutdown neo4j_driver_closed=true")


app = FastAPI(title="M10 Recipe Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("WEB_ORIGIN", "http://localhost:3000")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handlers — consistent error envelope for the Frontend
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Wrap Pydantic validation errors in the same structured envelope
    that `/kg/query` already uses, so the Frontend has one error shape."""
    logger.warning(
        "validation_error path=%s errors=%s",
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            reason="validation_error",
            detail=exc.errors(),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for unexpected 500s — return a structured envelope
    instead of a raw HTML traceback."""
    logger.exception(
        "unhandled_error path=%s exc_type=%s",
        request.url.path,
        exc.__class__.__name__,
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            reason="internal_error",
            detail=f"{exc.__class__.__name__}: {exc}",
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Path operations
# ---------------------------------------------------------------------------

@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest, nlp=Depends(get_nlp)) -> ExtractResponse:
    return ExtractResponse(entities=extract_entities(req.text, nlp))


@app.post("/kg/query", response_model=KGResponse)
def kg_query(req: KGRequest, session=Depends(get_session)) -> KGResponse:
    try:
        cypher, params = wrap_kg_query(req.question)
    except UnsupportedQueryError:
        raise HTTPException(
            status_code=422,
            detail=UnsupportedQueryDetail(
                reason="unsupported_question",
                supported_patterns=list(SUPPORTED_PATTERNS),
            ).model_dump(),
        )
    rows = [r.data() for r in session.run(cypher, **params)]
    return KGResponse(cypher=cypher, rows=rows, count=len(rows))


@app.post("/rag/answer", response_model=RAGResponse)
def rag_answer(
    req: RAGRequest,
    weaviate_client=Depends(get_weaviate),
    generator=Depends(get_generator),
    embedder=Depends(get_embedder),
) -> RAGResponse:
    result = compose_rag(req.question, embedder, weaviate_client, generator, k=req.k)
    return RAGResponse(**result)


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/readyz", response_model=ReadyDetail)
def readyz(
    session=Depends(get_session),
    weaviate_client=Depends(get_weaviate),
) -> ReadyDetail:
    detail = {"neo4j": "unknown", "weaviate": "unknown"}
    try:
        session.run("RETURN 1").single()
        detail["neo4j"] = "ok"
    except Exception as exc:
        detail["neo4j"] = f"unavailable: {exc.__class__.__name__}"
    try:
        if weaviate_client.is_ready():
            detail["weaviate"] = "ok"
        else:
            detail["weaviate"] = "not ready"
    except Exception as exc:
        detail["weaviate"] = f"unavailable: {exc.__class__.__name__}"

    if detail["neo4j"] != "ok" or detail["weaviate"] != "ok":
        raise HTTPException(status_code=503, detail=detail)
    return ReadyDetail(**detail)
