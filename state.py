"""LangGraph state schema for the finance-grade RAG workflow.

The state is intentionally explicit: every node reads and writes named
fields, while reducer annotations keep audit events, retries, and metrics
append-only across graph loops.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge node-level metrics without losing values written by previous nodes."""
    merged: dict[str, Any] = {}
    if left:
        merged.update(left)
    if right:
        merged.update(right)
    return merged


class FinanceRAGState(TypedDict, total=False):
    """Shared state carried through the LangGraph workflow."""

    # Request identity and compliance traceability.
    request_id: str
    thread_id: str
    user_id: str

    # Query routing.
    query: str
    original_query: str
    rewritten_query: str
    mode: Literal["auto", "sql", "rag", "hybrid", "simple"]
    route: Literal["sql", "rag", "hybrid", "simple"]

    # LangGraph/LangChain message history. add_messages preserves conversation turns.
    messages: Annotated[list[BaseMessage], add_messages]

    # Retrieval and reranking payloads.
    candidate_chunks: list[dict[str, Any]]
    ranked_chunks: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    rag_context: str
    top_relevance: float

    # SQL payloads.
    sql_result: dict[str, Any]
    sql_text: str

    # Loop control.
    retry_count: int
    max_retries: int

    # Final output.
    answer: str
    status: Literal["ok", "degraded", "error"]

    # Append-only observability and audit fields.
    retrieval_attempts: Annotated[list[dict[str, Any]], operator.add]
    events: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    latency: Annotated[dict[str, float], merge_dicts]
    token_usage: Annotated[dict[str, int], merge_dicts]
