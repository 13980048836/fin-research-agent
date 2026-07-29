"""
agents/specialist.py — Agent 基类

所有 Specialist Agent 的公共父类，封装 LLM 调用、流式输出、重试等通用逻辑。
"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

try:
    from langchain_community.chat_models.tongyi import ChatTongyi
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False

from config import get_config


@dataclass
class AgentResult:
    """Agent 执行结果"""
    content: str = ""
    metadata: dict = field(default_factory=dict)
    success: bool = True
    error: str | None = None


class BaseAgent(ABC):
    """Agent 基类"""

    name: str = "base"
    description: str = "基础 Agent"

    def __init__(self, config=None):
        self.cfg = config or get_config()
        self.llm_cfg = self.cfg.llm
        self._llm = None

    @property
    def llm(self):
        """懒加载 LLM 实例"""
        if self._llm is None:
            if not HAS_LANGCHAIN:
                raise ImportError(
                    "未安装 langchain 或 langchain-community。\n"
                    "请运行: pip install langchain langchain-community dashscope"
                )
            self._llm = ChatTongyi(
                model=self.llm_cfg.model,
                dashscope_api_key=self.llm_cfg.api_key,
                temperature=self.llm_cfg.temperature,
                max_tokens=self.llm_cfg.max_tokens,
                streaming=True,
            )
        return self._llm

    def _build_messages(self, system_prompt: str, user_prompt: str) -> list:
        """构建消息列表"""
        return [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

    async def run(self, **kwargs) -> AgentResult:
        """同步执行入口"""
        try:
            result = await self._execute(**kwargs)
            return result
        except Exception as e:
            return AgentResult(success=False, error=str(e))

    async def stream(self, **kwargs) -> AsyncIterator[str]:
        """流式输出"""
        try:
            async for chunk in self._stream(**kwargs):
                yield chunk
        except Exception as e:
            yield f"[Error] {e}"

    @abstractmethod
    async def _execute(self, **kwargs) -> AgentResult:
        """具体执行逻辑，子类实现"""
        ...

    async def _stream(self, **kwargs) -> AsyncIterator[str]:
        """流式执行逻辑，子类可覆盖"""
        result = await self._execute(**kwargs)
        yield result.content

    def _parse_json(self, text: str) -> dict | None:
        """尝试从文本中解析 JSON"""
        text = text.strip()
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 块
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass

        # 尝试提取第一个 {...}
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None
