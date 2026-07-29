"""
vector_store.py — FAISS 向量库管理

功能:
  1. 文档向量化（通义千问 Embedding API）
  2. FAISS 索引构建 + 持久化
  3. 增量更新
  4. 相似度检索 + MMR 重排

单例模式，全局共享一个向量库实例。
"""
import os
from pathlib import Path
from typing import Iterable

try:
    from langchain_community.embeddings import DashScopeEmbeddings
    from langchain_community.vectorstores import FAISS
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

from config import get_config


class VectorStoreManager:
    """FAISS 向量库管理器（单例）"""

    _instance = None

    def __new__(cls, config=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config=None):
        if self._initialized:
            return
        self.cfg = config or get_config()
        self.faiss_cfg = self.cfg.faiss
        self.emb_cfg = self.cfg.embedding
        self._embeddings = None
        self._store = None
        self._initialized = True

    @property
    def embeddings(self):
        """懒加载 Embedding 模型"""
        if self._embeddings is None:
            if not HAS_FAISS:
                raise ImportError(
                    "需要安装 faiss 相关依赖。\n"
                    "请运行: pip install faiss-cpu langchain-community dashscope"
                )
            self._embeddings = DashScopeEmbeddings(
                model=self.emb_cfg.model,
                dashscope_api_key=self.cfg.llm.api_key,
            )
        return self._embeddings

    @property
    def store(self):
        """获取 FAISS store（懒加载）"""
        if self._store is None:
            index_path = Path(self.faiss_cfg.index_path)
            if index_path.exists() and (index_path / "index.faiss").exists():
                self._store = FAISS.load_local(
                    str(index_path),
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )
            else:
                return None
        return self._store

    @property
    def is_built(self) -> bool:
        """向量库是否已构建"""
        return self.store is not None

    def build_from_documents(self, documents: list) -> "FAISS":
        """从文档列表构建向量库"""
        if not documents:
            raise ValueError("文档列表为空")

        print(f"📊 正在构建向量索引，共 {len(documents)} 个文档片段...")

        store = FAISS.from_documents(documents, self.embeddings)
        self._store = store

        # 持久化
        self.save()
        print(f"✅ 向量索引构建完成，已保存到: {self.faiss_cfg.index_path}")

        return store

    def save(self) -> None:
        """保存向量索引到磁盘"""
        if self._store is None:
            return
        index_path = Path(self.faiss_cfg.index_path)
        index_path.mkdir(parents=True, exist_ok=True)
        self._store.save_local(str(index_path))

    def add_documents(self, documents: list) -> None:
        """增量添加文档"""
        if self._store is None:
            self.build_from_documents(documents)
            return
        self._store.add_documents(documents)
        self.save()

    def similarity_search(self, query: str, k: int = None) -> list:
        """相似度检索"""
        if self.store is None:
            return []
        k = k or self.faiss_cfg.top_k
        return self.store.similarity_search(query, k=k)

    def similarity_search_with_score(self, query: str, k: int = None) -> list:
        """带分数的相似度检索"""
        if self.store is None:
            return []
        k = k or self.faiss_cfg.top_k
        return self.store.similarity_search_with_score(query, k=k)

    def max_marginal_relevance_search(
        self, query: str, k: int = None, fetch_k: int = 20, lambda_mult: float = 0.7
    ) -> list:
        """MMR 重排检索"""
        if self.store is None:
            return []
        k = k or self.faiss_cfg.top_k
        return self.store.max_marginal_relevance_search(
            query, k=k, fetch_k=fetch_k, lambda_mult=lambda_mult
        )

    def clear(self) -> None:
        """清空向量库"""
        self._store = None
        index_path = Path(self.faiss_cfg.index_path)
        if index_path.exists():
            import shutil
            shutil.rmtree(index_path)

    def rebuild_from_directory(self, docs_dir: str | Path) -> int:
        """从文档目录重建向量索引"""
        from doc_loader import DocumentLoader

        loader = DocumentLoader(self.cfg)
        result = loader.load_directory(docs_dir)

        if not result.documents:
            print(f"⚠️  目录中没有找到支持的文档: {docs_dir}")
            return 0

        self.build_from_documents(result.documents)
        return result.total_chunks


def get_vector_store() -> VectorStoreManager:
    """获取全局向量库单例"""
    return VectorStoreManager()
