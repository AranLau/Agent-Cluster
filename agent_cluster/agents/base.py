"""
Agent 基类 + AgentResult 数据结构
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from ..llm_client import LLMClient

AgentStatus = Literal["ok", "error", "skip"]
NextAction = Literal["continue", "stop", "revise", "retry"]


@dataclass
class AgentResult:
    """所有 Agent process() 的统一返回值"""

    status: AgentStatus = "ok"
    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    next_action: NextAction = "continue"
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "output": self.output,
            "metadata": self.metadata,
            "next_action": self.next_action,
            "elapsed_ms": self.elapsed_ms,
        }


class BaseAgent:
    """Agent 基类：名称 + system prompt + LLM 客户端"""

    def __init__(self, name: str, system_prompt: str, llm_client: LLMClient):
        self.name = name
        self.system_prompt = system_prompt
        self._llm = llm_client

    def process(self, input_data: Any) -> AgentResult:
        """子类必须实现"""
        raise NotImplementedError
