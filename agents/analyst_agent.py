"""
agents/analyst_agent.py — 投研分析师 Agent

负责:
  1. 整合 SQL 查询结果 + RAG 检索内容
  2. 生成结构化的投研分析报告
  3. 输出包含财务分析、研报观点、估值、风险提示的完整报告
"""
from .specialist import BaseAgent, AgentResult
from prompts import ANALYST_SYSTEM_PROMPT, ANALYST_USER_TEMPLATE, SIMPLE_ANALYSIS_PROMPT


class AnalystAgent(BaseAgent):
    """投研分析师 Agent"""

    name = "analyst_agent"
    description = "投研分析师，整合数据生成结构化分析报告"

    async def _execute(
        self,
        query: str,
        sql_results: str = "",
        rag_results: str = "",
        **kwargs,
    ) -> AgentResult:
        """生成投研分析报告"""
        if not sql_results and not rag_results:
            # 无数据时降级为简单回答
            return await self._simple_reply(query)

        user_prompt = ANALYST_USER_TEMPLATE.format(
            query=query,
            sql_results=sql_results or "_无 SQL 数据_",
            rag_results=rag_results or "_无研报数据_",
        )
        messages = self._build_messages(ANALYST_SYSTEM_PROMPT, user_prompt)

        response = await self.llm.ainvoke(messages)

        return AgentResult(
            content=response.content,
            metadata={
                "has_sql": bool(sql_results),
                "has_rag": bool(rag_results),
            },
            success=True,
        )

    async def _simple_reply(self, query: str) -> AgentResult:
        """无数据时的简单回复"""
        system_prompt = (
            "你是一位友好的投研助手。用户问了一个简单问题，"
            "请礼貌回复，并说明你可以提供的服务（财务数据查询、研报分析等）。"
            "回复要简洁，不超过 3 句话。"
        )
        messages = self._build_messages(system_prompt, f"用户说: {query}")
        response = await self.llm.ainvoke(messages)
        return AgentResult(content=response.content, success=True)

    async def stream_analysis(
        self,
        query: str,
        sql_results: str = "",
        rag_results: str = "",
    ):
        """流式生成分析报告"""
        user_prompt = ANALYST_USER_TEMPLATE.format(
            query=query,
            sql_results=sql_results or "_无 SQL 数据_",
            rag_results=rag_results or "_无研报数据_",
        )
        messages = self._build_messages(ANALYST_SYSTEM_PROMPT, user_prompt)

        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
