"""LangGraph node implementations for the upgraded finance RAG pipeline.

Nodes reuse the existing RouterAgent, SQLAgent, and AnalystAgent where useful,
while replacing FAISS/rank_bm25 retrieval with Milvus plus bm25s.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.analyst_agent import AnalystAgent
from agents.router_agent import RouterAgent
from agents.sql_agent import SQLAgent
from config import get_config
from state import FinanceRAGState


def stable_chunk_id(content: str, metadata: dict[str, Any] | None = None) -> str:
    """Deterministic chunk id (local copy, avoids hard dependency on milvus_client)."""
    import hashlib
    import json as _json

    metadata = metadata or {}
    key = {
        "source": metadata.get("source", ""),
        "page": metadata.get("page", ""),
        "chunk_index": metadata.get("chunk_index", metadata.get("index", "")),
        "content_sha1": hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest(),
    }
    raw = _json.dumps(key, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _event(node: str, status: str, **data: Any) -> dict[str, Any]:
    return {"ts": time.time(), "node": node, "status": status, **data}


def _run_async(coro):
    """Run existing async agents safely from sync LangGraph nodes."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


@lru_cache(maxsize=1)
def _router_agent() -> RouterAgent:
    return RouterAgent(config=get_config())


@lru_cache(maxsize=1)
def _sql_agent() -> SQLAgent:
    return SQLAgent(config=get_config())


@lru_cache(maxsize=1)
def _analyst_agent() -> AnalystAgent:
    return AnalystAgent(config=get_config())


@lru_cache(maxsize=1)
def _milvus():
    """Milvus client (lazy import; only used when Milvus backend is enabled)."""
    from milvus_client import MilvusVectorClient
    return MilvusVectorClient()


@lru_cache(maxsize=1)
def _hybrid_retriever():
    """Reuse the existing FAISS + BM25 + RRF retriever (no Milvus dependency).

    The LangGraph pipeline defaults to this FAISS-backed retriever so it runs
    locally without a Milvus server. Switch to Milvus by enabling the milvus
    backend in retriever_node.
    """
    from hybrid_retriever import HybridRetriever
    from vector_store import VectorStoreManager

    vs = VectorStoreManager()
    return HybridRetriever(vector_store=vs, config=get_config())


class BM25SKeywordIndex:
    """bm25s-backed lexical retriever with Chinese-friendly token expansion."""

    def __init__(self, index_path: str | Path | None = None):
        self.index_path = Path(index_path or os.getenv("BM25S_INDEX_PATH", "data/bm25s_index"))
        self._retriever = None

    def build_from_documents(self, documents: list[Any]) -> int:
        import bm25s

        corpus = []
        for idx, doc in enumerate(documents):
            content = self._content(doc)
            if not content:
                continue
            metadata = self._metadata(doc)
            metadata.setdefault("chunk_index", idx)
            corpus.append(
                {
                    "id": stable_chunk_id(content, metadata),
                    "content": content,
                    "source": metadata.get("source", ""),
                    "page": metadata.get("page", -1),
                    "metadata": metadata,
                }
            )

        if not corpus:
            return 0

        texts = [self._lexical_text(item["content"]) for item in corpus]
        tokens = bm25s.tokenize(texts, stopwords=None)
        retriever = bm25s.BM25(corpus=corpus)
        retriever.index(tokens)
        self.index_path.mkdir(parents=True, exist_ok=True)
        retriever.save(str(self.index_path), corpus=corpus)
        self._retriever = retriever
        return len(corpus)

    def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        import bm25s

        retriever = self._load()
        if retriever is None:
            return []

        query_tokens = bm25s.tokenize([self._lexical_text(query)], stopwords=None)
        docs, scores = retriever.retrieve(query_tokens, k=k)
        results: list[dict[str, Any]] = []
        if docs.size == 0:
            return results

        for idx in range(docs.shape[1]):
            item = docs[0, idx]
            score = float(scores[0, idx])
            if not isinstance(item, dict) or score <= 0:
                continue
            results.append(
                {
                    "id": str(item.get("id", "")),
                    "content": item.get("content", ""),
                    "source": item.get("source", ""),
                    "page": item.get("page", -1),
                    "metadata": item.get("metadata", {}),
                    "score": score,
                    "bm25_score": score,
                    "rank": idx + 1,
                    "retrieval_source": "bm25s",
                }
            )
        return results

    def _load(self):
        if self._retriever is not None:
            return self._retriever
        if not self.index_path.exists():
            return None

        import bm25s

        mmap = os.getenv("BM25S_MMAP", "true").lower() in {"1", "true", "yes"}
        self._retriever = bm25s.BM25.load(str(self.index_path), load_corpus=True, mmap=mmap)
        return self._retriever

    @staticmethod
    def _content(doc: Any) -> str:
        if hasattr(doc, "page_content"):
            return str(doc.page_content or "").strip()
        if isinstance(doc, dict):
            return str(doc.get("content") or doc.get("page_content") or doc.get("text") or "").strip()
        return str(doc).strip()

    @staticmethod
    def _metadata(doc: Any) -> dict[str, Any]:
        if hasattr(doc, "metadata"):
            return dict(doc.metadata or {})
        if isinstance(doc, dict):
            return dict(doc.get("metadata") or {})
        return {}

    @staticmethod
    def _lexical_text(text: str) -> str:
        latin = re.findall(r"[a-zA-Z0-9_.%+-]+", text.lower())
        cjk_terms: list[str] = []
        for block in re.findall(r"[\u4e00-\u9fff]+", text):
            cjk_terms.extend(block)
            cjk_terms.extend(block[i : i + 2] for i in range(max(len(block) - 1, 0)))
        return " ".join(latin + cjk_terms)


@lru_cache(maxsize=1)
def _bm25s() -> BM25SKeywordIndex:
    return BM25SKeywordIndex()


class BGEReranker:
    """Rerank candidates with BAAI/bge-large-zh-v1.5 embeddings."""

    def __init__(self):
        self.model_name = os.getenv("RERANK_MODEL", "BAAI/bge-large-zh-v1.5")
        self.device = os.getenv("RERANK_DEVICE", "cpu")
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        if not candidates:
            return []
        try:
            import numpy as np

            texts = [str(item.get("content", ""))[:1200] for item in candidates]
            embeddings = self.model.encode([query] + texts, normalize_embeddings=True, show_progress_bar=False)
            query_embedding = embeddings[0]
            doc_embeddings = embeddings[1:]
            scores = np.dot(doc_embeddings, query_embedding)
            reranked = []
            for item, score in zip(candidates, scores):
                enriched = dict(item)
                enriched["rerank_score"] = float(score)
                enriched["score"] = float(score)
                reranked.append(enriched)
            return sorted(reranked, key=lambda item: item.get("rerank_score", -math.inf), reverse=True)[:top_k]
        except Exception as exc:
            fallback = sorted(candidates, key=_relevance_proxy, reverse=True)[:top_k]
            for item in fallback:
                item.setdefault("rerank_error", str(exc))
            return fallback


@lru_cache(maxsize=1)
def _reranker() -> BGEReranker:
    return BGEReranker()


def query_analyzer_node(state: FinanceRAGState) -> dict[str, Any]:
    """Route the query into sql/rag/hybrid/simple before expensive work starts."""
    started = time.perf_counter()
    query = state["query"].strip()
    requested_mode = state.get("mode", "auto")
    errors: list[str] = []

    if requested_mode != "auto":
        route = requested_mode
        route_meta = {"mode": route, "confidence": 1.0, "route_type": "manual"}
    else:
        try:
            result = _run_async(_router_agent().run(query=query))
            route_meta = result.metadata if result and result.success else {}
            route = route_meta.get("mode", "hybrid")
        except Exception as exc:
            route = "hybrid"
            route_meta = {"mode": route, "confidence": 0.3, "route_type": "fallback"}
            errors.append(f"query_analyzer: {exc}")

    if route not in {"sql", "rag", "hybrid", "simple"}:
        route = "hybrid"

    return {
        "original_query": state.get("original_query", query),
        "route": route,
        "retry_count": int(state.get("retry_count", 0)),
        "max_retries": int(state.get("max_retries", os.getenv("RAG_MAX_REWRITE_RETRIES", "1"))),
        "messages": [HumanMessage(content=query)],
        "events": [_event("query_analyzer", "ok", route=route, metadata=route_meta)],
        "errors": errors,
        "latency": {"query_analyzer": time.perf_counter() - started},
    }


def sql_executor_node(state: FinanceRAGState) -> dict[str, Any]:
    """Run the existing guarded Text-to-SQL agent for sql and hybrid routes."""
    started = time.perf_counter()
    route = state.get("route", "hybrid")
    if route not in {"sql", "hybrid"}:
        return {"events": [_event("sql_executor", "skipped", route=route)]}

    try:
        result = _run_async(_sql_agent().run(query=state["query"]))
        payload = {
            "success": bool(result.success),
            "content": result.content,
            "error": result.error,
            "metadata": result.metadata,
        }
        return {
            "sql_result": payload,
            "sql_text": result.content if result.success else "",
            "events": [_event("sql_executor", "ok" if result.success else "degraded")],
            "errors": [] if result.success else [f"sql_executor: {result.error}"],
            "latency": {"sql_executor": time.perf_counter() - started},
            "token_usage": {"sql_estimated_tokens": _estimate_tokens(result.content)},
        }
    except Exception as exc:
        return {
            "sql_result": {"success": False, "content": "", "error": str(exc), "metadata": {}},
            "sql_text": "",
            "events": [_event("sql_executor", "error")],
            "errors": [f"sql_executor: {exc}"],
            "latency": {"sql_executor": time.perf_counter() - started},
        }


def retriever_node(state: FinanceRAGState) -> dict[str, Any]:
    """Retrieve candidates via the FAISS + BM25 + RRF hybrid retriever."""
    started = time.perf_counter()
    route = state.get("route", "hybrid")
    if route not in {"rag", "hybrid"}:
        return {"events": [_event("retriever", "skipped", route=route)]}

    query = state.get("rewritten_query") or state["query"]
    fetch_k = int(os.getenv("RAG_FETCH_K", "12"))
    errors: list[str] = []

    try:
        hits = _hybrid_retriever().search(
            query,
            top_k=fetch_k,
            use_bm25=True,
            use_vector=True,
            use_rerank=False,
            use_mmr=False,
        )
        candidates: list[dict[str, Any]] = []
        for rank, hit in enumerate(hits, start=1):
            doc = hit.get("doc") if isinstance(hit, dict) else None
            content = getattr(doc, "page_content", "") if doc is not None else str(hit.get("content", ""))
            metadata = (
                dict(getattr(doc, "metadata", {}) or {})
                if doc is not None
                else dict(hit.get("metadata", {}) or {})
            )
            score = float(hit.get("score", 0.0)) if isinstance(hit, dict) else 0.0
            candidates.append(
                {
                    "id": stable_chunk_id(content, metadata),
                    "content": content,
                    "source": metadata.get("source", ""),
                    "page": metadata.get("page", -1),
                    "metadata": metadata,
                    "score": score,
                    "vector_score": score,
                    "rank": rank,
                    "retrieval_source": "hybrid",
                }
            )
    except Exception as exc:
        candidates = []
        errors.append(f"hybrid_retriever: {exc}")

    return {
        "candidate_chunks": candidates,
        "retrieval_attempts": [
            {
                "query": query,
                "fused_hits": len(candidates),
                "retry_count": int(state.get("retry_count", 0)),
            }
        ],
        "events": [_event("retriever", "ok" if candidates else "empty", count=len(candidates))],
        "errors": errors,
        "latency": {"retriever": time.perf_counter() - started},
    }


def reranker_node(state: FinanceRAGState) -> dict[str, Any]:
    """Rerank retrieved candidates and build the compact RAG context."""
    started = time.perf_counter()
    route = state.get("route", "hybrid")
    if route not in {"rag", "hybrid"}:
        return {"events": [_event("reranker", "skipped", route=route)]}

    top_k = int(os.getenv("RAG_TOP_K", os.getenv("FAISS_TOP_K", "5")))
    candidates = state.get("candidate_chunks", [])
    ranked = _reranker().rerank(state.get("rewritten_query") or state["query"], candidates, top_k)
    top_relevance = _relevance_proxy(ranked[0]) if ranked else 0.0
    context = _format_context(ranked)
    citations = [
        {
            "source": item.get("source", ""),
            "page": item.get("page", -1),
            "score": round(float(item.get("score", 0.0)), 4),
            "id": item.get("id", ""),
        }
        for item in ranked
    ]
    return {
        "ranked_chunks": ranked,
        "rag_context": context,
        "citations": citations,
        "top_relevance": top_relevance,
        "events": [_event("reranker", "ok" if ranked else "empty", top_relevance=top_relevance)],
        "latency": {"reranker": time.perf_counter() - started},
    }


def query_rewriter_node(state: FinanceRAGState) -> dict[str, Any]:
    """Rewrite low-relevance queries once before retrying retrieval."""
    started = time.perf_counter()
    retry_count = int(state.get("retry_count", 0)) + 1
    original = state.get("original_query") or state["query"]
    previous = state.get("rewritten_query") or state["query"]

    try:
        from langchain_community.chat_models.tongyi import ChatTongyi

        llm = ChatTongyi(
            model=os.getenv("LLM_MODEL", "qwen3-max"),
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            temperature=0.0,
            max_tokens=256,
            streaming=False,
        )
        messages = [
            SystemMessage(
                content=(
                    "You rewrite Chinese financial research questions for retrieval. "
                    "Keep company names, reporting periods, metrics, and risk terms. "
                    "Return only the rewritten query."
                )
            ),
            HumanMessage(
                content=(
                    f"Original query: {original}\n"
                    f"Previous retrieval query: {previous}\n"
                    "Rewrite for annual-report and risk-factor retrieval."
                )
            ),
        ]
        response = llm.invoke(messages)
        rewritten = str(response.content).strip()[:500]
    except Exception:
        rewritten = f"{original} 财报 经营风险 财务指标 管理层讨论"

    return {
        "rewritten_query": rewritten,
        "retry_count": retry_count,
        "events": [_event("query_rewriter", "ok", retry_count=retry_count)],
        "latency": {"query_rewriter": time.perf_counter() - started},
    }


def generator_node(state: FinanceRAGState) -> dict[str, Any]:
    """Generate the final audited answer from SQL and RAG evidence."""
    started = time.perf_counter()
    sql_text = state.get("sql_text", "")
    rag_context = state.get("rag_context", "")
    query = state["query"]

    try:
        result = _run_async(_analyst_agent().run(query=query, sql_results=sql_text, rag_results=rag_context))
        if result.success:
            answer = result.content
            status = "ok"
            errors: list[str] = []
        else:
            answer = _fallback_answer(query, sql_text, rag_context, result.error or "generation failed")
            status = "degraded"
            errors = [f"generator: {result.error}"]
    except Exception as exc:
        answer = _fallback_answer(query, sql_text, rag_context, str(exc))
        status = "degraded"
        errors = [f"generator: {exc}"]

    token_usage = {
        "prompt_estimated_tokens": _estimate_tokens(query + sql_text + rag_context),
        "completion_estimated_tokens": _estimate_tokens(answer),
    }
    return {
        "answer": answer,
        "status": status,
        "events": [_event("generator", status)],
        "errors": errors,
        "latency": {"generator": time.perf_counter() - started},
        "token_usage": token_usage,
    }


def _rrf_fusion(vector_hits: list[dict[str, Any]], bm25_hits: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rrf_k = int(os.getenv("RRF_K", "60"))
    vector_weight = float(os.getenv("RRF_VECTOR_WEIGHT", "0.65"))
    bm25_weight = float(os.getenv("RRF_BM25_WEIGHT", "0.35"))
    by_id: dict[str, dict[str, Any]] = {}

    def add(items: list[dict[str, Any]], weight: float, field: str) -> None:
        for rank, item in enumerate(items, start=1):
            key = item.get("id") or stable_chunk_id(item.get("content", ""), item.get("metadata", {}))
            current = by_id.setdefault(key, dict(item, id=key, rrf_score=0.0))
            current["rrf_score"] = float(current.get("rrf_score", 0.0)) + weight / (rrf_k + rank)
            current[field] = item.get("score", 0.0)
            current["retrieval_source"] = (
                "hybrid" if current.get("retrieval_source") and current.get("retrieval_source") != item.get("retrieval_source") else item.get("retrieval_source", field)
            )

    add(vector_hits, vector_weight, "vector_score")
    add(bm25_hits, bm25_weight, "bm25_score")
    fused = list(by_id.values())
    fused.sort(key=lambda item: item.get("rrf_score", 0.0), reverse=True)
    for item in fused:
        item["score"] = _relevance_proxy(item)
    return fused[:limit]


def _relevance_proxy(item: dict[str, Any]) -> float:
    if "rerank_score" in item:
        return float(item["rerank_score"])
    if "vector_score" in item:
        return float(item["vector_score"])
    if "bm25_score" in item:
        bm25 = float(item["bm25_score"])
        return bm25 / (bm25 + 5.0)
    return min(1.0, float(item.get("rrf_score", 0.0)) * 20.0)


def _format_context(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for idx, item in enumerate(chunks, start=1):
        source = item.get("source", "unknown")
        page = item.get("page", "-")
        content = str(item.get("content", "")).strip()
        parts.append(f"[Document {idx}] Source: {source}, page: {page}\n{content}")
    return "\n\n".join(parts)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 3)


def _fallback_answer(query: str, sql_text: str, rag_context: str, error: str) -> str:
    evidence = rag_context or sql_text or "No reliable evidence was retrieved."
    return (
        f"Generation degraded for query: {query}\n\n"
        f"Reason: {error}\n\n"
        f"Available evidence:\n{evidence[:3000]}"
    )
