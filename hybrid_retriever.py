"""
hybrid_retriever.py — BM25 + 向量混合检索 + Cross-Encoder 重排

检索流程:
  1. BM25 关键词检索（基于词频匹配，擅长精确术语）
  2. FAISS 向量检索（基于语义相似度，擅长语义理解）
  3. RRF 融合（Reciprocal Rank Fusion，加权合并两路结果）
  4. Cross-Encoder 重排（精排，提升最终结果相关性）
     — 加载失败时自动降级：使用 RRF 融合结果，不再重试
     — 强制离线模式（HF_HUB_OFFLINE=1）避免网络不通卡死
  5. MMR 去重（多样性保证）

使用:
  from hybrid_retriever import HybridRetriever
  hr = HybridRetriever(vector_store=vsm)
  results = hr.search("茅台 2024 年业绩", top_k=5)
"""
import math
import os
import time
import pickle
import logging
import threading
from pathlib import Path
from typing import Optional

# ============================================================
# 强制离线环境设置（必须在 import sentence_transformers 之前）
# ============================================================
# 1) 国内 HuggingFace 镜像（兜底，离线模式下不生效但无害）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 2) 下载超时：10 秒强制熔断，避免长时间卡死
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")
# 3) 强制离线模式：不发起任何网络请求（有本地缓存则用缓存，无则直接失败）
#    如需在线下载模型，请设置环境变量 HF_HUB_OFFLINE=0
os.environ.setdefault("HF_HUB_OFFLINE", "1")
# 4) 请求超时同样设短
os.environ.setdefault("HF_DOWNLOAD_TIMEOUT", "10")

logger = logging.getLogger(__name__)

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False

try:
    from sentence_transformers import CrossEncoder
    HAS_CROSS_ENCODER = True
except ImportError:
    HAS_CROSS_ENCODER = False

# 标记 Cross-Encoder 是否已尝试加载过（避免每次检索都卡在网络重试上）
_CE_LOAD_TRIED = False
_CE_LOAD_SUCCESS = False
# Cross-Encoder 加载最大等待秒数（超过直接判失败，线程级保护）
_CE_LOAD_TIMEOUT = 15


class HybridRetriever:
    """BM25 + 向量混合检索器"""

    def __init__(self, vector_store=None, config=None):
        self.vector_store = vector_store
        self.config = config
        self._bm25 = None
        self._bm25_docs = []
        self._cross_encoder = None
        self._doc_store = []
        self._cross_encoder_model = "BAAI/bge-reranker-base"

        # BM25 索引持久化路径
        self._index_path = Path("data/bm25_index.pkl")

        # 自动从磁盘加载已保存的 BM25 索引
        self._try_load_index()

    def _try_load_index(self):
        """尝试从磁盘加载已保存的 BM25 索引"""
        if not HAS_BM25:
            return
        if not self._index_path.exists():
            return
        try:
            with open(self._index_path, "rb") as f:
                data = pickle.load(f)
            self._bm25 = data["bm25"]
            self._bm25_docs = data["docs"]
            self._doc_store = data["docs"]
            logger.info(f"📚 BM25 索引已从磁盘加载: {len(self._bm25_docs)} 个文档片段")
        except Exception as e:
            logger.warning(f"BM25 索引加载失败: {e}")

    def _save_index(self):
        """将 BM25 索引持久化到磁盘"""
        if self._bm25 is None or not self._bm25_docs:
            return
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._index_path, "wb") as f:
                pickle.dump({
                    "bm25": self._bm25,
                    "docs": self._bm25_docs,
                }, f)
            logger.info(f"📚 BM25 索引已保存到磁盘: {self._index_path}")
        except Exception as e:
            logger.warning(f"BM25 索引保存失败: {e}")

    def build_index(self, documents: list):
        """构建 BM25 索引（需要在向量库构建后调用）"""
        if not HAS_BM25:
            print("⚠️  rank_bm25 未安装，跳过 BM25 索引构建")
            return
        if not documents:
            return

        self._doc_store = documents
        tokenized_corpus = []
        for doc in documents:
            text = doc.page_content if hasattr(doc, 'page_content') else str(doc)
            tokens = self._tokenize(text)
            tokenized_corpus.append(tokens)

        self._bm25 = BM25Okapi(tokenized_corpus)
        self._bm25_docs = documents
        print(f"📚 BM25 索引构建完成: {len(documents)} 个文档片段")

        # 持久化到磁盘
        self._save_index()

    def _tokenize(self, text: str) -> list:
        """简单中文分词（基于字符 n-gram + 空格分词）"""
        tokens = []
        for word in text.split():
            tokens.append(word)
        import re
        chinese_chars = re.findall(r'[\u4e00-\u9fff]{2}', text)
        tokens.extend(chinese_chars)
        single_chars = re.findall(r'[\u4e00-\u9fff]', text)
        tokens.extend(single_chars)
        return list(set(tokens))

    def _bm25_search(self, query: str, k: int) -> list:
        """BM25 关键词检索"""
        if self._bm25 is None or not self._bm25_docs:
            return []

        tokenized_query = self._tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                doc = self._bm25_docs[idx]
                results.append({
                    "doc": doc,
                    "score": float(scores[idx]),
                    "index": idx,
                })
        return results

    def _vector_search(self, query: str, k: int) -> list:
        """向量检索"""
        if self.vector_store is None:
            return []
        try:
            docs = self.vector_store.similarity_search_with_score(query, k=k)
            results = []
            for doc, score in docs:
                results.append({
                    "doc": doc,
                    "score": float(score),
                })
            return results
        except Exception as e:
            logger.warning("Vector search with score failed, falling back to plain search: %s", e)
            docs = self.vector_store.similarity_search(query, k=k)
            return [
                {
                    "doc": doc,
                    "score": 0.0,
                }
                for doc in docs
            ]

    def _doc_key(self, doc) -> int:
        """文档唯一标识（用内容前 200 字符 hash，避免 id() 不一致问题）"""
        text = doc.page_content[:200] if hasattr(doc, 'page_content') else str(doc)[:200]
        return hash(text)

    def _rrf_fusion(self, bm25_results: list, vector_results: list, k: int = 60) -> list:
        """RRF 融合（Reciprocal Rank Fusion）

        注意：必须用文档内容 hash 做标识，不能用 id(doc)。
        因为 BM25 和向量检索返回的是不同的 Python 对象（即使内容相同），
        用 id() 会导致同一文档被当成两个不同文档，融合失效。
        """
        scores = {}
        docs_by_key = {}

        for rank, item in enumerate(bm25_results):
            key = self._doc_key(item["doc"])
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            if key not in docs_by_key:
                docs_by_key[key] = item["doc"]

        for rank, item in enumerate(vector_results):
            key = self._doc_key(item["doc"])
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            if key not in docs_by_key:
                docs_by_key[key] = item["doc"]

        fused = []
        for key, score in sorted(scores.items(), key=lambda x: -x[1]):
            fused.append({
                "doc": docs_by_key[key],
                "score": score,
            })

        return fused

    def _cross_encoder_rerank(self, query: str, candidates: list, top_k: int) -> list:
        """Cross-Encoder 重排（带快速降级 + 线程超时保护，避免卡死）"""
        global _CE_LOAD_TRIED, _CE_LOAD_SUCCESS

        if not HAS_CROSS_ENCODER:
            return candidates[:top_k]

        # 如果之前加载失败过，直接跳过（避免每次检索都卡在网络重试上）
        if _CE_LOAD_TRIED and not _CE_LOAD_SUCCESS:
            return candidates[:top_k]

        if self._cross_encoder is None:
            _CE_LOAD_TRIED = True

            # ---- 线程级超时保护：把加载操作放到子线程，超时直接判失败 ----
            _loaded_ce = [None]
            _load_err = [None]

            def _do_load():
                try:
                    # HF_HUB_OFFLINE=1 时不会联网；如果本地没有缓存就会立即抛异常
                    _loaded_ce[0] = CrossEncoder(
                        self._cross_encoder_model,
                        max_length=512,
                        device="cpu",  # 强制 CPU，避免 CUDA 相关额外等待
                    )
                except Exception as e:
                    _load_err[0] = e

            t = threading.Thread(target=_do_load, daemon=True)
            t.start()
            t.join(timeout=_CE_LOAD_TIMEOUT)

            if t.is_alive() or _loaded_ce[0] is None:
                _CE_LOAD_SUCCESS = False
                err_msg = f"加载超时（>{_CE_LOAD_TIMEOUT}s）" if t.is_alive() else str(_load_err[0] or "unknown")
                print(f"⚠️  Cross-Encoder 加载失败（将使用 RRF 融合结果，不影响检索）: {err_msg}")
                print("   提示: 如需启用重排，请确保网络通畅或模型已本地缓存，设置 HF_HUB_OFFLINE=0")
                return candidates[:top_k]

            self._cross_encoder = _loaded_ce[0]
            _CE_LOAD_SUCCESS = True
            print("🔄 Cross-Encoder 重排模型加载完成（离线缓存命中）")

        pairs = [(query, (item["doc"].page_content if hasattr(item["doc"], "page_content") else str(item["doc"]))[:512])
                 for item in candidates]
        try:
            scores = self._cross_encoder.predict(pairs, show_progress_bar=False)
            for i, item in enumerate(candidates):
                item["rerank_score"] = float(scores[i])
            candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        except Exception as e:
            print(f"⚠️  Cross-Encoder 重排失败: {e}")

        return candidates[:top_k]

    def _mmr_diversify(self, candidates: list, top_k: int, lambda_mult: float = 0.7) -> list:
        """MMR 多样性去重"""
        if len(candidates) <= top_k:
            return candidates

        selected = [candidates[0]]
        remaining = candidates[1:]

        for _ in range(top_k - 1):
            if not remaining:
                break
            best_idx = 0
            best_score = -float("inf")

            for i, cand in enumerate(remaining):
                relevance = cand.get("rerank_score", cand.get("score", 0))
                max_sim = 0
                for sel in selected:
                    sim = self._text_similarity(
                        cand["doc"].page_content[:100],
                        sel["doc"].page_content[:100]
                    )
                    max_sim = max(max_sim, sim)
                score = lambda_mult * relevance - (1 - lambda_mult) * max_sim
                if score > best_score:
                    best_score = score
                    best_idx = i

            selected.append(remaining[best_idx])
            remaining.pop(best_idx)

        return selected

    def _text_similarity(self, text1: str, text2: str) -> float:
        """简单文本相似度（基于字符集合 Jaccard）"""
        set1 = set(text1)
        set2 = set(text2)
        if not set1 or not set2:
            return 0.0
        intersection = set1 & set2
        union = set1 | set2
        return len(intersection) / len(union) if union else 0.0

    def search(
        self,
        query: str,
        top_k: int = 5,
        use_bm25: bool = True,
        use_vector: bool = True,
        use_rerank: bool = False,
        use_mmr: bool = False,
    ) -> list:
        """
        混合检索主入口

        Args:
            query: 查询文本
            top_k: 返回数量
            use_bm25: 启用 BM25 关键词检索
            use_vector: 启用向量语义检索
            use_rerank: 启用 Cross-Encoder 重排
            use_mmr: 启用 MMR 多样性去重

        Returns:
            list[dict]: 检索结果列表
        """
        # 候选扩展倍数：取 top_k*2，避免小库引入过多噪声候选
        fetch_k = top_k * 2

        # 1. BM25 关键词检索
        bm25_results = []
        if use_bm25 and HAS_BM25:
            bm25_results = self._bm25_search(query, fetch_k)

        # 2. 向量检索
        vector_results = []
        if use_vector and self.vector_store is not None:
            vector_results = self._vector_search(query, fetch_k)

        # 3. 融合
        if bm25_results and vector_results:
            fused = self._rrf_fusion(bm25_results, vector_results)
        elif bm25_results:
            fused = bm25_results
        elif vector_results:
            fused = vector_results
        else:
            return []

        # 4. Cross-Encoder 重排
        if use_rerank and HAS_CROSS_ENCODER and len(fused) > top_k:
            fused = self._cross_encoder_rerank(query, fused, top_k * 2)

        # 5. MMR 多样性
        if use_mmr and len(fused) > top_k:
            fused = self._mmr_diversify(fused, top_k)

        return fused[:top_k]

    def get_stats(self) -> dict:
        """获取检索器状态"""
        return {
            "bm25_indexed": self._bm25 is not None and len(self._bm25_docs),
            "total_docs": len(self._doc_store),
            "cross_encoder_available": HAS_CROSS_ENCODER,
            "cross_encoder_loaded": self._cross_encoder is not None,
            "vector_store_available": self.vector_store is not None and self.vector_store.is_built,
        }
