"""Milvus vector storage adapter for financial document chunks.

This module replaces the in-memory FAISS store with a persistent Milvus
collection. It keeps metadata explicit for auditability and leaves all secrets
in environment variables.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def stable_chunk_id(content: str, metadata: dict[str, Any] | None = None) -> str:
    """Create deterministic primary keys so migration can be retried safely."""
    metadata = metadata or {}
    key = {
        "source": metadata.get("source", ""),
        "page": metadata.get("page", ""),
        "chunk_index": metadata.get("chunk_index", metadata.get("index", "")),
        "content_sha1": hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest(),
    }
    raw = json.dumps(key, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class MilvusSettings:
    uri: str
    token: str
    collection_name: str
    dimension: int
    vector_field: str = "vector"
    metric_type: str = "COSINE"
    index_type: str = "AUTOINDEX"
    consistency_level: str = "Bounded"
    embedding_model: str = "text-embedding-v3"
    batch_size: int = 128
    timeout: float = 20.0

    @classmethod
    def from_env(cls) -> "MilvusSettings":
        return cls(
            uri=os.getenv("MILVUS_URI", "http://localhost:19530"),
            token=os.getenv("MILVUS_TOKEN", ""),
            collection_name=os.getenv("MILVUS_COLLECTION", "finance_report_chunks"),
            dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
            vector_field=os.getenv("MILVUS_VECTOR_FIELD", "vector"),
            metric_type=os.getenv("MILVUS_METRIC_TYPE", "COSINE"),
            index_type=os.getenv("MILVUS_INDEX_TYPE", "AUTOINDEX"),
            consistency_level=os.getenv("MILVUS_CONSISTENCY_LEVEL", "Bounded"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
            batch_size=int(os.getenv("MILVUS_BATCH_SIZE", "128")),
            timeout=float(os.getenv("MILVUS_TIMEOUT", "20")),
        )


class MilvusVectorClient:
    """Small Milvus facade used by graph nodes and migration scripts."""

    def __init__(self, settings: MilvusSettings | None = None, embedding_model: Any | None = None):
        self.settings = settings or MilvusSettings.from_env()
        self._client = None
        self._embeddings = embedding_model

    @property
    def client(self):
        if self._client is None:
            from pymilvus import MilvusClient

            kwargs: dict[str, Any] = {"uri": self.settings.uri}
            if self.settings.token:
                kwargs["token"] = self.settings.token
            self._client = MilvusClient(**kwargs)
        return self._client

    @property
    def embeddings(self):
        if self._embeddings is None:
            from langchain_community.embeddings import DashScopeEmbeddings

            self._embeddings = DashScopeEmbeddings(
                model=self.settings.embedding_model,
                dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            )
        return self._embeddings

    def ensure_collection(self) -> None:
        """Create the Milvus collection with explicit audit fields if needed."""
        if self.client.has_collection(self.settings.collection_name):
            return

        from pymilvus import DataType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field(
            field_name=self.settings.vector_field,
            datatype=DataType.FLOAT_VECTOR,
            dim=self.settings.dimension,
        )
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=2048)
        schema.add_field(field_name="doc_id", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="page", datatype=DataType.INT64)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="metadata_json", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="created_at", datatype=DataType.DOUBLE)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name=self.settings.vector_field,
            index_type=self.settings.index_type,
            metric_type=self.settings.metric_type,
        )

        self.client.create_collection(
            collection_name=self.settings.collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level=self.settings.consistency_level,
            timeout=self.settings.timeout,
        )

    def upsert_documents(self, documents: Iterable[Any], batch_size: int | None = None) -> int:
        """Embed and upsert LangChain Document-like objects into Milvus."""
        self.ensure_collection()
        batch_size = batch_size or self.settings.batch_size
        total = 0
        batch: list[Any] = []
        for doc in documents:
            batch.append(doc)
            if len(batch) >= batch_size:
                total += self._upsert_batch(batch)
                batch = []
        if batch:
            total += self._upsert_batch(batch)
        return total

    def _upsert_batch(self, documents: list[Any]) -> int:
        texts = [self._content(doc) for doc in documents]
        if not any(texts):
            return 0

        vectors = self.embeddings.embed_documents(texts)
        records = []
        now = time.time()
        for idx, (doc, text, vector) in enumerate(zip(documents, texts, vectors)):
            if not text:
                continue
            metadata = self._metadata(doc)
            page = self._int_or_default(metadata.get("page"), -1)
            chunk_index = self._int_or_default(metadata.get("chunk_index", metadata.get("index")), idx)
            source = str(metadata.get("source", ""))[:2048]
            doc_id = str(metadata.get("doc_id") or hashlib.sha1(source.encode("utf-8")).hexdigest())[:256]
            metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)[:65535]
            records.append(
                {
                    "id": stable_chunk_id(text, metadata),
                    self.settings.vector_field: vector,
                    "text": text[:65535],
                    "source": source,
                    "doc_id": doc_id,
                    "page": page,
                    "chunk_index": chunk_index,
                    "metadata_json": metadata_json,
                    "created_at": now,
                }
            )

        if not records:
            return 0

        if hasattr(self.client, "upsert"):
            self.client.upsert(collection_name=self.settings.collection_name, data=records)
        else:
            self.client.insert(collection_name=self.settings.collection_name, data=records)
        return len(records)

    def search(self, query: str, k: int = 10, filters: str = "") -> list[dict[str, Any]]:
        """Run vector search and normalize Milvus hits for downstream graph nodes."""
        self.ensure_collection()
        query_vector = self.embeddings.embed_query(query)
        results = self.client.search(
            collection_name=self.settings.collection_name,
            data=[query_vector],
            anns_field=self.settings.vector_field,
            filter=filters,
            limit=k,
            output_fields=["text", "source", "doc_id", "page", "chunk_index", "metadata_json"],
            search_params={"metric_type": self.settings.metric_type, "params": {}},
            timeout=self.settings.timeout,
        )
        hits = results[0] if results else []
        normalized: list[dict[str, Any]] = []
        for rank, hit in enumerate(hits, start=1):
            entity = hit.get("entity", {}) or {}
            metadata = self._loads_metadata(entity.get("metadata_json"))
            normalized.append(
                {
                    "id": str(hit.get("id", entity.get("id", ""))),
                    "content": entity.get("text", ""),
                    "source": entity.get("source", metadata.get("source", "")),
                    "page": entity.get("page", metadata.get("page", -1)),
                    "metadata": metadata,
                    "score": float(hit.get("distance", hit.get("score", 0.0))),
                    "vector_score": float(hit.get("distance", hit.get("score", 0.0))),
                    "rank": rank,
                    "retrieval_source": "milvus",
                }
            )
        return normalized

    def count(self) -> int:
        try:
            stats = self.client.get_collection_stats(self.settings.collection_name)
            return int(stats.get("row_count", 0))
        except Exception:
            return 0

    def healthcheck(self) -> dict[str, Any]:
        try:
            exists = self.client.has_collection(self.settings.collection_name)
            return {"ok": True, "collection": self.settings.collection_name, "exists": exists, "rows": self.count()}
        except Exception as exc:
            return {"ok": False, "collection": self.settings.collection_name, "error": str(exc)}

    @staticmethod
    def _content(doc: Any) -> str:
        if hasattr(doc, "page_content"):
            return str(doc.page_content or "").strip()
        if isinstance(doc, dict):
            return str(doc.get("page_content") or doc.get("content") or doc.get("text") or "").strip()
        return str(doc).strip()

    @staticmethod
    def _metadata(doc: Any) -> dict[str, Any]:
        if hasattr(doc, "metadata"):
            return dict(doc.metadata or {})
        if isinstance(doc, dict):
            return dict(doc.get("metadata") or {})
        return {}

    @staticmethod
    def _loads_metadata(value: Any) -> dict[str, Any]:
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except Exception:
            return {}

    @staticmethod
    def _int_or_default(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default


def get_milvus_client() -> MilvusVectorClient:
    return MilvusVectorClient()
