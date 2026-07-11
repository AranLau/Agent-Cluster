"""
门卫+路由 Agent（纯文本，AI Translate 边界）
- 永不接触原始文件（图片/xlsx），只消费 content.md 纯文本
- 确保非多模态模型也能正常运行
- 牺牲原始排版/视觉信息，换取标准化下游处理
"""

import time

from .base import AgentResult, BaseAgent

GUARD_SYSTEM_PROMPT = """你是一个 Agent 集群的门卫和路由器。你的唯一职责是：基于用户输入的内容，判断意图并决定路由方向。

## 重要前提
你收到的内容是经过 OCR/文本提取转写的 markdown，可能已经损失了部分视觉排版信息。
请基于文本的可读内容进行意图判断，而非依赖原始的视觉格式。

## 路由分类规则

### 1. analysis（分析请求）
用户要求对内容进行理解、总结、分析、评估，但不产生文件/代码/操作。
- "分析这份报告"
- "总结一下这些截图说了什么"
- "评估这个方案的可行性"
- "这些数据说明了什么"

### 2. execution（执行请求）
用户要求产出具体成果：生成文件、执行代码、调用工具、操作数据等。
- "帮我创建 xxx.py"
- "把这些数据整理成表格"
- "根据截图内容生成一份报告"
- "调用 MCP 工具检查 xxx"

### 3. meta_training（元训练请求）
用户要求对历史任务进行回顾、评估、规则更新等元操作。
- "回顾之前所有任务的质量"
- "更新审议规则"
- "对历史案例做批量评估"

### 4. invalid（无效请求）
- 纯闲聊（"你好"、"今天天气怎么样"）
- 要求 RTFM/STFW（"帮我读一下那个文档"、"帮我搜一下"）→ 标注无效
- 与系统能力完全无关的请求

## 输出格式
请严格以 JSON 格式返回：
```json
{
  "intent": "analysis | execution | meta_training | invalid",
  "summary": "一句话概括用户意图",
  "confidence": 0.0~1.0,
  "reasoning": "分类理由"
}
```
"""


class GuardAgent(BaseAgent):
    """门卫路由 Agent — 纯文本，只读 content.md"""

    def __init__(self, llm_client):
        super().__init__("Guard", GUARD_SYSTEM_PROMPT, llm_client)

    def process(self, task) -> AgentResult:
        """
        输入：Task 对象（仅使用 content_md 纯文本）
        输出：路由决策
        """
        t0 = time.perf_counter()

        # 构建消息（仅纯文本）
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"## 用户原始输入\n{task.input_text}\n\n## OCR 转写内容（conversion_status: {task.conversion_status}）\n{task.content_md}",
            },
        ]

        # 请求 JSON 格式路由决策
        result = self._llm.chat_json(messages)

        if result["ok"]:
            data = result["data"]
            intent = data.get("intent", "invalid")
            # 降低 partial/failed 场景下的 confidence
            confidence = data.get("confidence", 0.7)
            if task.conversion_status in ("partial", "failed"):
                confidence = min(confidence, 0.5)

            return AgentResult(
                status="ok",
                output=json.dumps(data, ensure_ascii=False),
                metadata={
                    "intent": intent,
                    "summary": data.get("summary", ""),
                    "confidence": confidence,
                    "conversion_quality": task.conversion_status,
                    "reasoning": data.get("reasoning", ""),
                },
                next_action="continue",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )
        else:
            return AgentResult(
                status="ok",
                output=result.get("raw", ""),
                metadata={
                    "intent": "analysis",  # fallback
                    "summary": "JSON 解析失败，降级为 analysis",
                    "confidence": 0.3,
                    "conversion_quality": task.conversion_status,
                    "parse_error": True,
                },
                next_action="continue",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )


import json
