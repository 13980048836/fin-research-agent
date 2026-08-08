"""Production FastAPI entrypoint for the LangGraph finance RAG service."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from config import get_config
from graph import DEFAULT_RECURSION_LIMIT, close_graph_resources, get_compiled_graph, run_finance_graph
from milvus_client import MilvusVectorClient
from nodes import BM25SKeywordIndex

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    HAS_RATE_LIMIT = True
except ImportError:
    HAS_RATE_LIMIT = False


API_KEY = os.getenv("API_KEY", "")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
MAX_DOCUMENT_BYTES = int(os.getenv("MAX_DOCUMENT_MB", "50")) * 1024 * 1024
API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "30"))
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".md", ".pptx"}

if HAS_PROMETHEUS:
    HTTP_REQUESTS = Counter("finrag_http_requests_total", "HTTP requests", ["method", "path", "status"])
    HTTP_LATENCY = Histogram(
        "finrag_http_request_latency_seconds",
        "HTTP request latency",
        ["method", "path"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30),
    )
    GRAPH_LATENCY = Histogram(
        "finrag_graph_latency_seconds",
        "LangGraph total latency",
        buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30),
    )
    RETRIEVAL_LATENCY = Histogram(
        "finrag_retrieval_latency_seconds",
        "Retriever node latency",
        buckets=(0.01, 0.03, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
    )
    GRAPH_REWRITE_LOOPS = Histogram(
        "finrag_graph_rewrite_loops",
        "Query rewrite loop count",
        buckets=(0, 1, 2, 3, 5),
    )
    LLM_TOKENS = Counter("finrag_llm_tokens_total", "Estimated LLM token usage", ["kind"])
    ERRORS = Counter("finrag_errors_total", "Application errors", ["kind"])

if HAS_RATE_LIMIT:
    limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"))


def rate_limit(limit_value: str):
    if HAS_RATE_LIMIT and RATE_LIMIT_PER_MINUTE > 0:
        return limiter.limit(limit_value)

    def decorator(func):
        return func

    return decorator


class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    mode: Literal["auto", "sql", "rag", "hybrid", "simple"] = "auto"
    user_id: str = Field("anonymous", max_length=128)
    thread_id: str | None = Field(None, max_length=128)
    max_retries: int = Field(default=1, ge=0, le=3)


class AnalyzeResponse(BaseModel):
    code: int
    message: str
    request_id: str
    thread_id: str
    data: dict


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.environ.setdefault("LANGSMITH_TRACING", os.getenv("LANGSMITH_TRACING", "false"))
    os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGSMITH_PROJECT", "fin-research-langgraph"))
    get_config().ensure_dirs()
    await run_in_threadpool(get_compiled_graph)
    yield
    close_graph_resources()


app = FastAPI(
    title="Finance Research LangGraph API",
    description="Financial PDF RAG and risk-analysis service powered by LangGraph, Milvus, bm25s, and Qwen.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:8050").split(",") if item.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

if HAS_RATE_LIMIT:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        if HAS_PROMETHEUS:
            ERRORS.labels("unhandled").inc()
        raise
    finally:
        if HAS_PROMETHEUS:
            path = request.url.path
            HTTP_REQUESTS.labels(request.method, path, str(status_code)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    public_paths = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}
    if request.url.path in public_paths or not API_KEY:
        return await call_next(request)
    incoming_key = request.headers.get("X-API-Key", "")
    if incoming_key != API_KEY:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid X-API-Key"})
    return await call_next(request)


@app.get("/health")
async def health_check():
    milvus = MilvusVectorClient().healthcheck()
    return {
        "status": "ok" if milvus.get("ok") else "degraded",
        "version": "1.0.0",
        "llm_model": os.getenv("LLM_MODEL", "qwen3-max"),
        "milvus": milvus,
        "langsmith_tracing": os.getenv("LANGSMITH_TRACING", "false"),
    }


@app.get("/metrics")
async def metrics():
    if not HAS_PROMETHEUS:
        raise HTTPException(status_code=503, detail="prometheus_client is not installed")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v2/analyze", response_model=AnalyzeResponse)
@rate_limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def analyze(req: AnalyzeRequest, request: Request):
    request_id = str(uuid.uuid4())
    thread_id = req.thread_id or str(uuid.uuid4())
    initial_state = {
        "request_id": request_id,
        "thread_id": thread_id,
        "user_id": req.user_id,
        "query": req.query,
        "mode": req.mode,
        "max_retries": req.max_retries,
        "retrieval_attempts": [],
        "events": [],
        "errors": [],
        "latency": {},
        "token_usage": {},
    }

    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            run_in_threadpool(run_finance_graph, initial_state, thread_id),
            timeout=API_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        if HAS_PROMETHEUS:
            ERRORS.labels("timeout").inc()
        raise HTTPException(status_code=504, detail="LangGraph execution timed out") from exc
    except Exception as exc:
        if HAS_PROMETHEUS:
            ERRORS.labels("graph").inc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    graph_latency = time.perf_counter() - started
    latency = result.get("latency", {})
    token_usage = result.get("token_usage", {})
    if HAS_PROMETHEUS:
        GRAPH_LATENCY.observe(graph_latency)
        RETRIEVAL_LATENCY.observe(float(latency.get("retriever", 0.0)))
        GRAPH_REWRITE_LOOPS.observe(float(result.get("retry_count", 0)))
        LLM_TOKENS.labels("prompt").inc(int(token_usage.get("prompt_estimated_tokens", 0)))
        LLM_TOKENS.labels("completion").inc(int(token_usage.get("completion_estimated_tokens", 0)))

    return AnalyzeResponse(
        code=0 if result.get("status") in {"ok", "degraded"} else 1,
        message=result.get("status", "ok"),
        request_id=request_id,
        thread_id=thread_id,
        data={
            "answer": result.get("answer", ""),
            "route": result.get("route", ""),
            "top_relevance": result.get("top_relevance", 0.0),
            "citations": result.get("citations", []),
            "sql": result.get("sql_result", {}),
            "latency": {**latency, "graph_total": graph_latency},
            "token_usage": token_usage,
            "rewrite_loops": result.get("retry_count", 0),
            "events": result.get("events", []),
            "errors": result.get("errors", []),
        },
    )


@app.post("/api/v2/documents/upload")
@rate_limit(f"{max(1, RATE_LIMIT_PER_MINUTE // 4)}/minute")
async def upload_document(request: Request, file: UploadFile = File(...)):
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {extension}")

    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail=f"Document exceeds {MAX_DOCUMENT_BYTES // 1024 // 1024}MB")

    cfg = get_config()
    upload_dir = Path(cfg.docs_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = (upload_dir / f"{uuid.uuid4().hex}_{filename}").resolve()
    if upload_dir.resolve() not in save_path.parents:
        raise HTTPException(status_code=400, detail="Invalid file path")
    save_path.write_bytes(content)

    indexed = await run_in_threadpool(_index_uploaded_file, save_path)
    return {"code": 0, "message": "success", "data": indexed}


@app.get("/api/v2/stats")
async def stats():
    milvus = MilvusVectorClient().healthcheck()
    bm25_path = Path(os.getenv("BM25S_INDEX_PATH", "data/bm25s_index"))
    return {
        "code": 0,
        "data": {
            "milvus": milvus,
            "bm25s_index_exists": bm25_path.exists(),
            "checkpointer": os.getenv("LANGGRAPH_CHECKPOINTER", "sqlite"),
            "recursion_limit": DEFAULT_RECURSION_LIMIT,
            "rag_top_k": int(os.getenv("RAG_TOP_K", os.getenv("FAISS_TOP_K", "5"))),
        },
    }


def _index_uploaded_file(path: Path) -> dict[str, int | str]:
    from doc_loader import DocumentLoader

    cfg = get_config()
    loader = DocumentLoader(cfg)
    uploaded_docs = loader.load_file(path)
    milvus_count = MilvusVectorClient().upsert_documents(uploaded_docs)

    # Rebuild bm25s over the full document root so lexical retrieval stays complete.
    all_docs = loader.load_directory(cfg.docs_dir).documents
    bm25_count = BM25SKeywordIndex().build_from_documents(all_docs)
    return {
        "file": str(path),
        "uploaded_chunks": len(uploaded_docs),
        "milvus_upserted": milvus_count,
        "bm25s_indexed": bm25_count,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "fastapi_app:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
    )
