"""
agents — 多 Agent 协作模块

Agent 架构:
  RouterAgent    → 路由决策：判断走哪条链路
  SQLAgent       → SQL 链路：自然语言 → SQL → 结构化数据
  RetrieverAgent → RAG 链路：自然语言 → 向量检索 → 文档片段
  AnalystAgent   → 分析师：整合各链路结果，生成投研报告
"""
from .specialist import BaseAgent, AgentResult
from .router_agent import RouterAgent
from .sql_agent import SQLAgent
from .retriever_agent import RetrieverAgent
from .analyst_agent import AnalystAgent

__all__ = [
    "BaseAgent",
    "AgentResult",
    "RouterAgent",
    "SQLAgent",
    "RetrieverAgent",
    "AnalystAgent",
]
