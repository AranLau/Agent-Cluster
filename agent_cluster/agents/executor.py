"""
实干家 Agent — 直接开工，不对结果进行自我反思
- analysis 模式：纯 AI 对话，生成分析报告
- execution 模式：AI 对话 + 可选的 MCP tool calling
"""

import time

from .base import AgentResult, BaseAgent

EXECUTOR_SYSTEM_PROMPT = """你是一个 Agent 集群的实干家（Executor）。你的唯一职责是：收到任务后直接执行，不对结果进行自我反思或质量评估。

## 核心原则
1. 直接开工，不质疑任务
2. 基于提供的 content.md 内容进行分析或执行
3. 结果尽可能结构化（Markdown 格式）
4. 不在输出中包含"我认为"、"我觉得"等自我反思性语言
5. 如果有 MCP 工具可用，优先使用工具执行操作而非纯文本回复

## 注意
- content.md 是 OCR 转写产物，可能包含 [OCR_FAILED: ...] 占位符
- 遇到占位符时，基于可读部分继续执行，不要因部分失败而停止
"""


class ExecutorAgent(BaseAgent):
    """实干家 Agent"""

    def __init__(self, llm_client):
        super().__init__("Executor", EXECUTOR_SYSTEM_PROMPT, llm_client)

    def process(self, task, intent: str, mcp_client=None) -> AgentResult:
        """
        执行任务。
        intent: 'analysis' | 'execution'
        mcp_client: 可选 MCP 客户端
        """
        t0 = time.perf_counter()

        # 构建提示
        if intent == "analysis":
            task_prompt = _build_analysis_prompt(task)
        else:
            task_prompt = _build_execution_prompt(task)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task_prompt},
        ]

        # MCP 工具（如有）
        tools = None
        if intent == "execution" and mcp_client:
            try:
                tools = mcp_client.list_tools()
            except Exception:
                tools = None

        # 执行
        if tools:
            result = self._llm.chat(messages, tools=tools)
            # 处理 tool calls（最多一轮）
            tool_calls = result.get("tool_calls")
            if tool_calls:
                tool_results = self._execute_tool_calls(mcp_client, tool_calls)
                # 追加工具结果到消息
                messages.append(
                    {
                        "role": "assistant",
                        "content": result.get("content") or "",
                        "tool_calls": tool_calls,  # type: ignore[dict-item]
                    }
                )
                for tr in tool_results:
                    messages.append(tr)
                result = self._llm.chat(messages)
        else:
            result = self._llm.chat(messages)

        return AgentResult(
            status="ok",
            output=result.get("content", ""),
            metadata={
                "intent": intent,
                "mcp_used": bool(tools),
                "token_usage": result.get("usage", {}),
            },
            next_action="continue",
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    def _execute_tool_calls(self, mcp_client, tool_calls: list[dict]) -> list[dict]:
        """执行 MCP 工具调用，返回 OpenAI 格式的工具结果消息"""
        results = []
        for tc in tool_calls:
            try:
                output = mcp_client.call_tool(tc["name"], tc.get("arguments", {}))
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(output),
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": f"[TOOL_ERROR: {e}]",
                    }
                )
        return results


# ------------------------------------------------------------------
# Prompt 构建
# ------------------------------------------------------------------


def _build_analysis_prompt(task) -> str:
    return f"""## 用户请求
{task.input_text}

## 任务内容（OCR 转写，conversion_status: {task.conversion_status}）
{task.content_md}

请对以上内容进行分析，生成结构化的分析报告。"""


def _build_execution_prompt(task) -> str:
    return f"""## 用户请求
{task.input_text}

## 任务内容（OCR 转写，conversion_status: {task.conversion_status}）
{task.content_md}

请基于以上内容执行用户请求。如有 MCP 工具可用，优先使用工具。"""
