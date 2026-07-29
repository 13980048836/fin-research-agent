"""
agents/router_agent.py — 路由 Agent

负责:
  判断用户问题应该走 sql / rag / hybrid / simple 哪条路径。
"""
from .specialist import BaseAgent, AgentResult
from prompts import ROUTER_SYSTEM_PROMPT, ROUTER_USER_TEMPLATE


class RouterAgent(BaseAgent):
    """路由决策 Agent"""

    name = "router_agent"
    description = "问题路由，判断走 SQL 链路还是 RAG 链路"

    # 常见关键词快速路由（不经过 LLM，降低延迟）
    SQL_KEYWORDS = [
        "营收", "利润", "净利润", "毛利率", "净利率", "ROE", "ROA",
        "市值", "股价", "市盈率", "PE", "PB", "增长率", "复合增长率",
        "增速", "排名", "排行", "对比", "比较", "多少", "几",
        "每股收益", "EPS", "分红", "负债率",
    ]

    RAG_KEYWORDS = [
        "研报", "报告", "分析", "点评", "观点", "看法",
        "深度", "公告", "分红公告", "股权激励",
        "怎么看", "怎么样", "投资价值", "前景",
    ]

    async def _execute(self, query: str, **kwargs) -> AgentResult:
        """路由决策"""
        # 快速路由：关键词匹配
        fast_mode = self._fast_route(query)
        if fast_mode:
            return AgentResult(
                content=fast_mode,
                metadata={"mode": fast_mode, "confidence": 0.7, "route_type": "keyword"},
                success=True,
            )

        # LLM 路由
        user_prompt = ROUTER_USER_TEMPLATE.format(query=query)
        messages = self._build_messages(ROUTER_SYSTEM_PROMPT, user_prompt)

        response = await self.llm.ainvoke(messages)
        parsed = self._parse_json(response.content)

        if parsed and "mode" in parsed:
            mode = parsed["mode"]
            confidence = parsed.get("confidence", 0.5)
            if mode not in ("sql", "rag", "hybrid", "simple"):
                mode = "hybrid"
            return AgentResult(
                content=mode,
                metadata={"mode": mode, "confidence": confidence, "route_type": "llm"},
                success=True,
            )

        # 兜底：走 hybrid
        return AgentResult(
            content="hybrid",
            metadata={"mode": "hybrid", "confidence": 0.5, "route_type": "fallback"},
            success=True,
        )

    def _fast_route(self, query: str) -> str | None:
        """基于关键词的快速路由"""
        query_lower = query.lower()

        has_sql = any(kw.lower() in query_lower for kw in self.SQL_KEYWORDS)
        has_rag = any(kw.lower() in query_lower for kw in self.RAG_KEYWORDS)

        if has_sql and has_rag:
            return "hybrid"
        if has_sql:
            return "sql"
        if has_rag:
            return "rag"

        # 极短文本（寒暄类）
        if len(query) < 5:
            return "simple"

        return None
