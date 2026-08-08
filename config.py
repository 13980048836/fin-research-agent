"""
config.py — 统一配置中心

所有配置项集中管理，优先从环境变量读取，其次使用默认值。
支持 .env 文件加载（python-dotenv）。

注意: HuggingFace 镜像配置已移至 .env 文件，确保在 import
     sentence_transformers 之前就已生效（dotenv 自动加载）。
"""
import os
import threading

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# .env 加载必须在最前面，确保所有子模块的 import 都能读到正确的环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# HuggingFace 镜像配置（从 .env 读取，默认值保底）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

BASE_DIR = Path(__file__).resolve().parent


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "tongyi"))
    api_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "qwen3-max"))
    temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.1")))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "2048")))
    timeout: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT", "60")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "3")))

    def validate(self) -> None:
        if not self.api_key:
            raise ValueError(
                "请配置 DASHSCOPE_API_KEY 环境变量。\n"
                "获取地址: https://dashscope.console.aliyun.com/apiKey"
            )


@dataclass
class EmbeddingConfig:
    """向量嵌入配置"""
    provider: str = field(default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "tongyi"))
    model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-v3"))
    dimension: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIMENSION", "1024")))
    batch_size: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_BATCH_SIZE", "256")))


@dataclass
class DatabaseConfig:
    """数据库配置"""
    type: str = field(default_factory=lambda: os.getenv("DB_TYPE", "sqlite"))
    path: str = field(default_factory=lambda: os.getenv("DB_PATH", str(BASE_DIR / "data" / "finance.db")))
    read_only: bool = field(default_factory=lambda: os.getenv("DB_READ_ONLY", "true").lower() == "true")
    timeout: int = field(default_factory=lambda: int(os.getenv("DB_TIMEOUT", "30")))
    max_rows: int = field(default_factory=lambda: int(os.getenv("DB_MAX_ROWS", "1000")))


@dataclass
class FAISSConfig:
    """FAISS 向量库配置"""
    index_path: str = field(default_factory=lambda: os.getenv(
        "FAISS_INDEX_PATH", str(BASE_DIR / "data" / "faiss_index")
    ))
    index_type: Literal["flat", "ivf", "hnsw"] = field(
        default_factory=lambda: os.getenv("FAISS_INDEX_TYPE", "flat")
    )
    top_k: int = field(default_factory=lambda: int(os.getenv("FAISS_TOP_K", "5")))
    rerank_enabled: bool = field(
        default_factory=lambda: os.getenv("RAG_RERANK_ENABLED", "false").lower() == "true"
    )
    mmr_enabled: bool = field(default_factory=lambda: os.getenv("FAISS_MMR_ENABLED", "false").lower() == "true")
    mmr_lambda: float = field(default_factory=lambda: float(os.getenv("FAISS_MMR_LAMBDA", "0.7")))
    score_threshold: float = field(default_factory=lambda: float(os.getenv("FAISS_SCORE_THRESHOLD", "0.3")))


@dataclass
class MilvusConfig:
    """Milvus vector database configuration for the LangGraph stack."""
    uri: str = field(default_factory=lambda: os.getenv("MILVUS_URI", "http://localhost:19530"))
    token: str = field(default_factory=lambda: os.getenv("MILVUS_TOKEN", ""))
    collection: str = field(default_factory=lambda: os.getenv("MILVUS_COLLECTION", "finance_report_chunks"))
    vector_field: str = field(default_factory=lambda: os.getenv("MILVUS_VECTOR_FIELD", "vector"))
    metric_type: str = field(default_factory=lambda: os.getenv("MILVUS_METRIC_TYPE", "COSINE"))
    index_type: str = field(default_factory=lambda: os.getenv("MILVUS_INDEX_TYPE", "AUTOINDEX"))
    batch_size: int = field(default_factory=lambda: int(os.getenv("MILVUS_BATCH_SIZE", "128")))


@dataclass
class GraphConfig:
    """LangGraph runtime controls."""
    checkpointer: Literal["sqlite", "redis"] = field(
        default_factory=lambda: os.getenv("LANGGRAPH_CHECKPOINTER", "sqlite")
    )
    recursion_limit: int = field(default_factory=lambda: int(os.getenv("LANGGRAPH_RECURSION_LIMIT", "8")))
    relevance_threshold: float = field(default_factory=lambda: float(os.getenv("RAG_RELEVANCE_THRESHOLD", "0.35")))
    max_rewrite_retries: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_REWRITE_RETRIES", "1")))


@dataclass
class SplitterConfig:
    """文档切分配置"""
    strategy: Literal["recursive", "character", "markdown"] = field(
        default_factory=lambda: os.getenv("SPLIT_STRATEGY", "recursive")
    )
    chunk_size: int = field(default_factory=lambda: int(os.getenv("SPLIT_CHUNK_SIZE", "500")))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv("SPLIT_CHUNK_OVERLAP", "100")))


@dataclass
class SQLExecutorConfig:
    """SQL 执行器配置"""
    keyword_filter_enabled: bool = True
    syntax_validation_enabled: bool = True
    readonly_transaction_enabled: bool = True
    row_limit_enabled: bool = True
    timeout_enabled: bool = True
    timeout_seconds: int = field(default_factory=lambda: int(os.getenv("SQL_TIMEOUT", "30")))
    max_rows: int = field(default_factory=lambda: int(os.getenv("SQL_MAX_ROWS", "1000")))


@dataclass
class CrawlerConfig:
    """爬虫配置（默认关闭）"""
    enabled: bool = field(default_factory=lambda: os.getenv("CRAWLER_ENABLED", "false").lower() == "true")
    delay: float = field(default_factory=lambda: float(os.getenv("CRAWLER_DELAY", "2.0")))
    max_pages: int = field(default_factory=lambda: int(os.getenv("CRAWLER_MAX_PAGES", "50")))
    save_dir: str = field(default_factory=lambda: os.getenv(
        "CRAWLER_SAVE_DIR", str(BASE_DIR / "data" / "docs" / "crawled")
    ))


@dataclass
class CleanerConfig:
    """文档数据清洗配置"""
    enabled: bool = True
    remove_headers_footers: bool = True
    merge_broken_lines: bool = True
    deduplicate_text: bool = True
    clean_special_chars: bool = True
    normalize_whitespace: bool = True
    min_line_length: int = 2
    similarity_threshold: float = 0.85


@dataclass
class PDFConfig:
    """智能 PDF 处理配置"""
    text_threshold: int = field(default_factory=lambda: int(os.getenv("PDF_TEXT_THRESHOLD", "50")))
    ocr_backend: str = field(default_factory=lambda: os.getenv("PDF_OCR_BACKEND", "paddleocr"))
    vl_model: str = field(default_factory=lambda: os.getenv("PDF_VL_MODEL", "qwen-vl-max"))
    vision_for_tables: bool = field(default_factory=lambda: os.getenv("PDF_VISION_FOR_TABLES", "true").lower() == "true")
    render_dpi: int = field(default_factory=lambda: int(os.getenv("PDF_RENDER_DPI", "200")))


@dataclass
class AppConfig:
    """应用总配置"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    faiss: FAISSConfig = field(default_factory=FAISSConfig)
    milvus: MilvusConfig = field(default_factory=MilvusConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    splitter: SplitterConfig = field(default_factory=SplitterConfig)
    cleaner: CleanerConfig = field(default_factory=CleanerConfig)
    pdf: PDFConfig = field(default_factory=PDFConfig)
    sql_executor: SQLExecutorConfig = field(default_factory=SQLExecutorConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)

    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")
    docs_dir: Path = field(default_factory=lambda: BASE_DIR / "data" / "docs")

    def ensure_dirs(self) -> None:
        """确保必要目录存在"""
        for d in [self.data_dir, self.docs_dir, self.docs_dir / "research_pdf",
                  self.docs_dir / "announcements", self.docs_dir / "roadshow_ppt",
                  self.docs_dir / "crawled"]:
            d.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        """校验关键配置"""
        self.llm.validate()
        self.ensure_dirs()


_config: AppConfig | None = None
_config_lock = threading.Lock()


def get_config() -> AppConfig:
    """获取全局单例配置（线程安全双检锁）"""
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = AppConfig()
    return _config
