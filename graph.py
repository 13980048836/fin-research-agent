"""LangGraph construction and invocation helpers.

The graph uses conditional edges for route selection and low-relevance retry,
and compiles with a Redis checkpointer in production or SQLite locally.
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from nodes import (
    generator_node,
    query_analyzer_node,
    query_rewriter_node,
    reranker_node,
    retriever_node,
    sql_executor_node,
)
from state import FinanceRAGState


DEFAULT_RECURSION_LIMIT = int(os.getenv("LANGGRAPH_RECURSION_LIMIT", "8"))
DEFAULT_RELEVANCE_THRESHOLD = float(os.getenv("RAG_RELEVANCE_THRESHOLD", "0.35"))

_graph = None
_checkpoint_context = None
_lock = threading.Lock()


def route_after_analysis(state: FinanceRAGState) -> str:
    route = state.get("route", "hybrid")
    if route == "sql":
        return "sql"
    if route == "rag":
        return "rag"
    if route == "simple":
        return "simple"
    return "hybrid"


def route_after_sql(state: FinanceRAGState) -> str:
    return "retriever" if state.get("route") == "hybrid" else "generator"


def route_after_rerank(state: FinanceRAGState) -> str:
    threshold = float(os.getenv("RAG_RELEVANCE_THRESHOLD", str(DEFAULT_RELEVANCE_THRESHOLD)))
    retry_count = int(state.get("retry_count", 0))
    max_retries = int(state.get("max_retries", os.getenv("RAG_MAX_REWRITE_RETRIES", "1")))
    top_relevance = float(state.get("top_relevance", 0.0))
    if top_relevance < threshold and retry_count < max_retries:
        return "rewrite"
    return "generate"


def build_graph(checkpointer: Any | None = None):
    builder = StateGraph(FinanceRAGState)
    builder.add_node("query_analyzer", query_analyzer_node)
    builder.add_node("sql_executor", sql_executor_node)
    builder.add_node("retriever", retriever_node)
    builder.add_node("reranker", reranker_node)
    builder.add_node("query_rewriter", query_rewriter_node)
    builder.add_node("generator", generator_node)

    builder.add_edge(START, "query_analyzer")
    builder.add_conditional_edges(
        "query_analyzer",
        route_after_analysis,
        {
            "sql": "sql_executor",
            "rag": "retriever",
            "hybrid": "sql_executor",
            "simple": "generator",
        },
    )
    builder.add_conditional_edges(
        "sql_executor",
        route_after_sql,
        {
            "retriever": "retriever",
            "generator": "generator",
        },
    )
    builder.add_edge("retriever", "reranker")
    builder.add_conditional_edges(
        "reranker",
        route_after_rerank,
        {
            "rewrite": "query_rewriter",
            "generate": "generator",
        },
    )
    builder.add_edge("query_rewriter", "retriever")
    builder.add_edge("generator", END)
    return builder.compile(checkpointer=checkpointer)


def build_checkpointer():
    kind = os.getenv("LANGGRAPH_CHECKPOINTER", "sqlite").strip().lower()
    strict = os.getenv("LANGGRAPH_CHECKPOINTER_STRICT", "false").lower() in {"1", "true", "yes"}

    if kind == "redis":
        try:
            from langgraph.checkpoint.redis import RedisSaver

            ttl_minutes = int(os.getenv("LANGGRAPH_CHECKPOINT_TTL_MINUTES", "0"))
            ttl = None
            if ttl_minutes > 0:
                ttl = {"default_ttl": ttl_minutes, "refresh_on_read": True}
            context = RedisSaver.from_conn_string(os.getenv("REDIS_URL", "redis://localhost:6379/0"), ttl=ttl)
            saver = context.__enter__()
            saver.setup()
            return saver, context
        except Exception:
            if strict:
                raise

    from langgraph.checkpoint.sqlite import SqliteSaver

    path = Path(os.getenv("LANGGRAPH_SQLITE_PATH", "data/langgraph_checkpoints.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    context = SqliteSaver.from_conn_string(str(path))
    saver = context.__enter__()
    return saver, context


def get_compiled_graph():
    global _graph, _checkpoint_context
    if _graph is None:
        with _lock:
            if _graph is None:
                checkpointer, context = build_checkpointer()
                _checkpoint_context = context
                _graph = build_graph(checkpointer=checkpointer)
    return _graph


def build_invoke_config(
    thread_id: str,
    recursion_limit: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": recursion_limit or DEFAULT_RECURSION_LIMIT,
        "metadata": metadata or {},
        "tags": ["finance-rag", "langgraph"],
    }


def run_finance_graph(initial_state: FinanceRAGState, thread_id: str | None = None) -> FinanceRAGState:
    graph = get_compiled_graph()
    resolved_thread_id = thread_id or initial_state.get("thread_id") or str(uuid.uuid4())
    state = dict(initial_state)
    state.setdefault("thread_id", resolved_thread_id)
    state.setdefault("request_id", str(uuid.uuid4()))
    config = build_invoke_config(
        resolved_thread_id,
        metadata={
            "request_id": state["request_id"],
            "user_id": state.get("user_id", "anonymous"),
            "route_hint": state.get("mode", "auto"),
        },
    )
    return graph.invoke(state, config=config)


def close_graph_resources() -> None:
    global _graph, _checkpoint_context
    if _checkpoint_context is not None:
        _checkpoint_context.__exit__(None, None, None)
    _checkpoint_context = None
    _graph = None
