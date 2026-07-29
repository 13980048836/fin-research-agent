"""
orchestrator.py — 多 Agent 编排器

负责:
  1. 接收用户问题，调用 RouterAgent 做路由决策
  2. 根据路由结果，协调 SQLAgent / RetrieverAgent 并行执行
  3. 汇总各链路结果，交给 AnalystAgent 生成最终报告
  4. 处理各环节的降级容错

协作流程:
  用户输入 → Router → [SQL Agent] + [RAG Agent] → Analyst → 输出报告
                   ↓
                simple 模式 → 直接回复
"""
import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from config import get_config
from agents import (
    RouterAgent,
    SQLAgent,
    RetrieverAgent,
    AnalystAgent,
    AgentResult,
)

try:
    from hybrid_retriever import HybridRetriever
except ImportError:
    HybridRetriever = None


@dataclass
class PipelineResult:
    """完整链路执行结果"""
    query: str
    mode: str = "hybrid"
    router_result: dict = field(default_factory=dict)
    sql_result: AgentResult | None = None
    rag_result: AgentResult | None = None
    analyst_result: AgentResult | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None and self.analyst_result is not None

    @property
    def final_content(self) -> str:
        if self.analyst_result and self.analyst_result.success:
            return self.analyst_result.content
        if self.error:
            return f"分析失败: {self.error}"
        return "暂无分析结果"


class Orchestrator:
    """多 Agent 编排器"""

    def __init__(self, vector_store=None, config=None):
        self.cfg = config or get_config()
        self._vector_store = vector_store

        # 初始化混合检索器
        self._hybrid = None
        if HybridRetriever is not None and vector_store is not None:
            self._hybrid = HybridRetriever(vector_store=vector_store, config=self.cfg)

        self.router = RouterAgent(config=self.cfg)
        self.sql_agent = SQLAgent(config=self.cfg)
        self.retriever = RetrieverAgent(
            vector_store=vector_store, config=self.cfg,
            hybrid_retriever=self._hybrid,
        )
        self.analyst = AnalystAgent(config=self.cfg)

    async def analyze(self, query: str, mode: str = "auto") -> PipelineResult:
        """
        执行完整分析链路。

        Args:
            query: 用户问题
            mode: auto/sql/rag/hybrid/simple

        Returns:
            PipelineResult 完整结果
        """
        result = PipelineResult(query=query)

        try:
            # Step 1: 路由
            if mode == "auto":
                route_res = await self.router.run(query=query)
                result.mode = route_res.metadata.get("mode", "hybrid")
                result.router_result = route_res.metadata
            else:
                result.mode = mode
                result.router_result = {"mode": mode, "route_type": "manual"}

            # Step 2: 按模式执行对应链路（并行）
            sql_text = ""
            rag_text = ""

            tasks = []
            if result.mode in ("sql", "hybrid"):
                tasks.append(self._run_sql(query, result))
            else:
                tasks.append(asyncio.sleep(0))  # 占位

            if result.mode in ("rag", "hybrid"):
                tasks.append(self._run_rag(query, result))
            else:
                tasks.append(asyncio.sleep(0))

            await asyncio.gather(*tasks)

            if result.sql_result and result.sql_result.success:
                sql_text = result.sql_result.content
            if result.rag_result and result.rag_result.success:
                rag_text = result.rag_result.content

            # Step 3: 分析师生成报告
            if result.mode == "simple":
                result.analyst_result = await self.analyst.run(
                    query=query, sql_results="", rag_results=""
                )
            else:
                result.analyst_result = await self.analyst.run(
                    query=query,
                    sql_results=sql_text,
                    rag_results=rag_text,
                )

        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"

        return result

    async def stream_analyze(
        self, query: str, mode: str = "auto"
    ) -> AsyncIterator[dict]:
        """
        流式分析，产出 SSE 事件。

        Yields:
            dict: {"event": "...", "data": {...}}
        """
        try:
            # Step 1: 路由
            if mode == "auto":
                route_res = await self.router.run(query=query)
                actual_mode = route_res.metadata.get("mode", "hybrid")
                confidence = route_res.metadata.get("confidence", 0.5)
            else:
                actual_mode = mode
                confidence = 1.0

            yield {"event": "router", "data": {"mode": actual_mode, "confidence": confidence}}

            # Step 2: SQL 链路
            sql_text = ""
            sql_rows = []
            sql_columns = []
            if actual_mode in ("sql", "hybrid"):
                yield {"event": "sql_start", "data": {"message": "正在查询数据库..."}}
                sql_res = await self.sql_agent.run(query=query)
                sql_text = sql_res.content if sql_res.success else ""
                sql_rows = sql_res.metadata.get("raw_rows", [])
                sql_columns = sql_res.metadata.get("columns", [])
                yield {
                    "event": "sql_end",
                    "data": {
                        "row_count": sql_res.metadata.get("row_count", 0),
                        "sql": sql_res.metadata.get("sql", ""),
                        "passed_checks": sql_res.metadata.get("passed_checks", []),
                        "success": sql_res.success,
                        "columns": sql_columns,
                        "rows": sql_rows,
                    },
                }

            # Step 3: RAG 链路
            rag_text = ""
            if actual_mode in ("rag", "hybrid"):
                yield {"event": "rag_start", "data": {"message": "正在检索研报..."}}
                rag_res = await self.retriever.run(query=query)
                rag_text = rag_res.content if rag_res.success else ""
                chunks = rag_res.metadata.get("chunks", [])
                sources = [
                    f"{c.get('source', '未知')} (第{c.get('page', '-')}页)"
                    for c in chunks
                ]
                yield {
                    "event": "rag_end",
                    "data": {
                        "chunk_count": rag_res.metadata.get("total", 0),
                        "success": rag_res.success,
                        "sources": sources,
                    },
                }

            # Step 4: 分析师流式输出
            yield {"event": "report_start", "data": {"message": "正在生成分析报告..."}}

            full_content = []
            async for token in self.analyst.stream_analysis(
                query=query, sql_results=sql_text, rag_results=rag_text
            ):
                full_content.append(token)
                yield {"event": "report_token", "data": {"token": token}}

            yield {
                "event": "done",
                "data": {
                    "total_tokens": len("".join(full_content)),
                    "mode": actual_mode,
                },
            }

        except Exception as e:
            yield {"event": "error", "data": {"message": str(e)}}

    async def _run_sql(self, query: str, result: PipelineResult) -> None:
        """执行 SQL 链路（带降级）"""
        try:
            result.sql_result = await self.sql_agent.run(query=query)
        except Exception as e:
            result.sql_result = AgentResult(success=False, error=str(e))

    async def _run_rag(self, query: str, result: PipelineResult) -> None:
        """执行 RAG 链路（带降级）"""
        try:
            if self._vector_store is None:
                result.rag_result = AgentResult(
                    success=False, error="向量库未初始化，跳过 RAG 链路"
                )
                return
            result.rag_result = await self.retriever.run(query=query)
        except Exception as e:
            result.rag_result = AgentResult(success=False, error=str(e))


# ==================== 全局单例缓存（线程安全）====================

_orchestrator_instance: Orchestrator | None = None
_orchestrator_lock = threading.Lock()


def get_orchestrator_cached(vector_store=None, config=None) -> Orchestrator:
    """获取线程安全的全局 Orchestrator 单例（双检锁）"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        with _orchestrator_lock:
            if _orchestrator_instance is None:
                _orchestrator_instance = Orchestrator(
                    vector_store=vector_store, config=config
                )
    return _orchestrator_instance
