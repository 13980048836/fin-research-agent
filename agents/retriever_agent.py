"""
agents/retriever_agent.py — RAG 检索 Agent（混合检索版）

检索链路:
  1. BM25 关键词检索（精确术语匹配）
  2. FAISS 向量检索（语义相似度）
  3. RRF 融合（两路结果加权合并）
  4. Cross-Encoder 重排（精排）
  5. MMR 去重（多样性保证）
"""
from .specialist import BaseAgent, AgentResult
from prompts import RETRIEVER_SYSTEM_PROMPT, RETRIEVER_USER_TEMPLATE


class RetrieverAgent(BaseAgent):
    """RAG 检索 Agent — 支持混合检索"""

    name = "retriever_agent"
    description = "文档检索与整理，从知识库中查找相关信息"

    def __init__(self, vector_store=None, config=None, hybrid_retriever=None):
        super().__init__(config)
        self.vector_store = vector_store
        self.hybrid = hybrid_retriever

    async def _execute(self, query: str, top_k: int = None, **kwargs) -> AgentResult:
        """混合检索并整理文档"""
        top_k = top_k or self.cfg.faiss.top_k

        if self.vector_store is None:
            return AgentResult(
                content="",
                metadata={"chunks": [], "retrieval_mode": "none"},
                success=False,
                error="向量库未初始化",
            )

        # 1. 使用混合检索器（如果可用）
        if self.hybrid is not None:
            try:
                results = self.hybrid.search(
                    query=query,
                    top_k=top_k,
                    use_bm25=True,
                    use_vector=True,
                    use_rerank=True,
                    use_mmr=True,
                )
                if results:
                    return self._format_results(results, top_k, "hybrid")
            except Exception as e:
                print(f"⚠️  混合检索失败，回退到纯向量检索: {e}")

        # 2. 回退: 纯向量检索 + MMR
        docs = self.vector_store.similarity_search(query, k=top_k * 2)

        if not docs:
            return AgentResult(
                content="未检索到相关文档。",
                metadata={"chunks": [], "retrieval_mode": "vector_only"},
                success=True,
            )

        if self.cfg.faiss.mmr_enabled and hasattr(self.vector_store, 'max_marginal_relevance_search'):
            docs = self.vector_store.max_marginal_relevance_search(
                query, k=top_k, fetch_k=top_k * 2,
                lambda_mult=self.cfg.faiss.mmr_lambda,
            )
        else:
            docs = docs[:top_k]

        results = [{"doc": doc, "score": 0.0} for doc in docs]
        return self._format_results(results, top_k, "vector_only")

    def _format_results(self, results: list, top_k: int, mode: str) -> AgentResult:
        """格式化检索结果"""
        chunks = []
        context_parts = []

        for i, item in enumerate(results[:top_k], 1):
            doc = item["doc"]
            source = doc.metadata.get("source", "未知来源")
            page = doc.metadata.get("page", "-")
            content = doc.page_content.strip()
            score = item.get("score", 0)
            rerank_score = item.get("rerank_score", None)

            chunks.append({
                "index": i,
                "source": source,
                "page": page,
                "content": content,
                "score": round(score, 4),
                "rerank_score": round(rerank_score, 4) if rerank_score else None,
                "metadata": doc.metadata,
            })
            context_parts.append(
                f"【文档 {i}】来源: {source} (第{page}页)\n{content}\n"
            )

        context_text = "\n".join(context_parts)

        return AgentResult(
            content=context_text,
            metadata={
                "chunks": chunks,
                "total": len(results[:top_k]),
                "retrieval_mode": mode,
            },
            success=True,
        )

    def search_simple(self, query: str, top_k: int = None) -> list:
        """同步检索（非流式，快速调用）"""
        top_k = top_k or self.cfg.faiss.top_k
        if self.vector_store is None:
            return []
        if self.hybrid is not None:
            results = self.hybrid.search(query, top_k=top_k)
            return [r["doc"] for r in results]
        return self.vector_store.similarity_search(query, k=top_k)