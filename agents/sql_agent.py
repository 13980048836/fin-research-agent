"""
agents/sql_agent.py — SQL 生成 Agent

负责:
  1. Schema 理解：根据用户问题筛选相关表和字段
  2. SQL 生成：将自然语言转为可执行 SQL
"""
import re
from .specialist import BaseAgent, AgentResult
from prompts import (
    SQL_AGENT_SYSTEM_PROMPT,
    SQL_AGENT_USER_TEMPLATE,
    DEFAULT_SCHEMA_DESCRIPTION,
)
from executor import get_executor
from db import get_schema_info


class SQLAgent(BaseAgent):
    """SQL 生成 Agent"""

    name = "sql_agent"
    description = "Text-to-SQL 生成器，将自然语言转为 SQL 查询"

    def __init__(self, config=None):
        super().__init__(config)
        self.executor = get_executor()
        self._schema_cache: str | None = None

    def get_schema_description(self) -> str:
        """获取 Schema 描述（优先用缓存）"""
        if self._schema_cache is not None:
            return self._schema_cache

        try:
            tables = get_schema_info()
            if tables:
                parts = []
                for t in tables:
                    cols = ", ".join(
                        f"{c['name']}({c['type']})" for c in t["columns"]
                    )
                    parts.append(f"### {t['table_name']}\n- {cols}")
                self._schema_cache = "可用表:\n" + "\n\n".join(parts)
            else:
                self._schema_cache = DEFAULT_SCHEMA_DESCRIPTION
        except Exception:
            self._schema_cache = DEFAULT_SCHEMA_DESCRIPTION

        return self._schema_cache

    async def _execute(self, query: str, **kwargs) -> AgentResult:
        """生成 SQL 并执行"""
        schema_ctx = self.get_schema_description()

        system_prompt = SQL_AGENT_SYSTEM_PROMPT.format(schema_context=schema_ctx)
        user_prompt = SQL_AGENT_USER_TEMPLATE.format(query=query)
        messages = self._build_messages(system_prompt, user_prompt)

        # 生成 SQL
        response = await self.llm.ainvoke(messages)
        sql = self._extract_sql(response.content)

        if not sql:
            return AgentResult(
                success=False,
                error="未能从 LLM 响应中提取到有效 SQL",
                metadata={"raw_response": response.content[:200]},
            )

        # 执行 SQL
        exec_result = self.executor.execute(sql)

        return AgentResult(
            content=exec_result.to_markdown_table(),
            metadata={
                "sql": exec_result.sql,
                "row_count": exec_result.row_count,
                "columns": exec_result.columns,
                "passed_checks": exec_result.passed_checks,
                "failed_check": exec_result.failed_check,
                "raw_rows": exec_result.rows,
            },
            success=exec_result.is_success,
            error=exec_result.error,
        )

    async def generate_sql_only(self, query: str) -> str:
        """仅生成 SQL，不执行"""
        schema_ctx = self.get_schema_description()
        system_prompt = SQL_AGENT_SYSTEM_PROMPT.format(schema_context=schema_ctx)
        user_prompt = SQL_AGENT_USER_TEMPLATE.format(query=query)
        messages = self._build_messages(system_prompt, user_prompt)

        response = await self.llm.ainvoke(messages)
        return self._extract_sql(response.content)

    def _extract_sql(self, text: str) -> str:
        """从 LLM 响应中提取 SQL"""
        text = text.strip()

        # 尝试提取 ```sql ... ```
        match = re.search(r"```(?:sql)?\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # 尝试找 SELECT 开头
        match = re.search(r"(SELECT[\s\S]+?)(?:;|$)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(";")

        # 直接返回
        return text if text.upper().startswith("SELECT") else ""
