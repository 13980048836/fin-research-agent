"""Migrate an existing LangChain FAISS index into Milvus and bm25s."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from milvus_client import MilvusSettings, MilvusVectorClient
from nodes import BM25SKeywordIndex


def load_faiss_documents(index_path: str | Path) -> tuple[list[Any], int]:
    from langchain_community.embeddings import DashScopeEmbeddings
    from langchain_community.vectorstores import FAISS

    embeddings = DashScopeEmbeddings(
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
    )
    store = FAISS.load_local(
        str(index_path),
        embeddings,
        allow_dangerous_deserialization=True,
    )
    docstore = getattr(store, "docstore", None)
    if hasattr(docstore, "_dict"):
        docs = list(docstore._dict.values())
    else:
        docs = [docstore.search(doc_id) for doc_id in store.index_to_docstore_id.values()]
    return docs, int(getattr(store.index, "ntotal", len(docs)))


def migrate(args: argparse.Namespace) -> dict[str, Any]:
    docs, faiss_vectors = load_faiss_documents(args.faiss_path)
    settings = MilvusSettings.from_env()
    if args.collection:
        settings.collection_name = args.collection
    client = MilvusVectorClient(settings=settings)
    upserted = client.upsert_documents(docs, batch_size=args.batch_size)

    bm25s_indexed = 0
    if args.rebuild_bm25s:
        bm25s_indexed = BM25SKeywordIndex(args.bm25s_path).build_from_documents(docs)

    validation = validate(client, docs, args.validate_samples)
    return {
        "faiss_vectors": faiss_vectors,
        "faiss_documents": len(docs),
        "milvus_upserted": upserted,
        "milvus_rows": client.count(),
        "bm25s_indexed": bm25s_indexed,
        "validation": validation,
    }


def validate(client: MilvusVectorClient, docs: list[Any], samples: int) -> list[dict[str, Any]]:
    checks = []
    for doc in docs[: max(samples, 0)]:
        content = getattr(doc, "page_content", str(doc))
        query = content[:80].strip()
        if not query:
            continue
        hits = client.search(query, k=1)
        checks.append(
            {
                "query_preview": query,
                "hit_count": len(hits),
                "top_score": hits[0]["score"] if hits else 0.0,
                "top_source": hits[0].get("source", "") if hits else "",
            }
        )
    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate LangChain FAISS data to Milvus.")
    parser.add_argument("--faiss-path", default=os.getenv("FAISS_INDEX_PATH", "data/faiss_index"))
    parser.add_argument("--collection", default=os.getenv("MILVUS_COLLECTION", "finance_report_chunks"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("MILVUS_BATCH_SIZE", "128")))
    parser.add_argument("--rebuild-bm25s", action="store_true")
    parser.add_argument("--bm25s-path", default=os.getenv("BM25S_INDEX_PATH", "data/bm25s_index"))
    parser.add_argument("--validate-samples", type=int, default=3)
    return parser.parse_args()


if __name__ == "__main__":
    import json

    print(json.dumps(migrate(parse_args()), ensure_ascii=False, indent=2))
