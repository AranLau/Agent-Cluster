"""
审议者 Agent — 极高标准的反思者
- 加载 rules.json 规则库进行审查
- RTFM/STFW 检测 → 标注需求无效
- MVP 原则检查 → 拒绝过度工程
- 范围蔓延检测 → 警告
"""

import json
import time
from pathlib import Path

from .base import AgentResult, BaseAgent

REVIEWER_SYSTEM_PROMPT = """你是一个 Agent 集群的审议者（Reviewer）。你拥有极高标准的反思能力，对标 MVP 原则。

## 核心职责
1. 审查实干家的输出结果是否符合用户需求
2. 根据规则库逐条检查
3. 给出审议结论：pass（通过）/ reject（拒绝）/ revise（需修改）

## 审查标准
- 是否解决了用户的核心诉求？
- 输出是否过度工程？（MVP 原则）
- 是否存在范围蔓延？
- 实干家是否进行了自我反思？（禁止）
- 原始需求是否属于 RTFM/STFW 类型？（标注无效）

## 输出格式
请严格以 JSON 格式返回：
```json
{
  "verdict": "pass | reject | revise",
  "rules_triggered": ["规则ID列表"],
  "comments": "审议意见",
  "ocr_risk": true/false,
  "suggestion": "修改建议（verdict=revise时）"
}
```
"""


class ReviewerAgent(BaseAgent):
    """审议者 Agent"""

    def __init__(self, llm_client, rules_path: Path | None = None):
        super().__init__("Reviewer", REVIEWER_SYSTEM_PROMPT, llm_client)
        self._rules_path = (
            rules_path or Path(__file__).resolve().parent.parent / "rules" / "rules.json"
        )
        self._rules: list[dict] = []

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def load_rules(self) -> list[dict]:
        """加载规则库"""
        if self._rules_path.exists():
            try:
                data = json.loads(self._rules_path.read_text(encoding="utf-8"))
                self._rules = data.get("rules", [])
            except (json.JSONDecodeError, OSError):
                self._rules = []
        return self._rules

    def process(self, task, executor_output: str, intent: str) -> AgentResult:
        """
        审议实干家的输出。
        """
        t0 = time.perf_counter()
        rules = self.load_rules()

        # 快速本地规则检查（不消耗 LLM 调用）
        local_flags = self._local_check(task.input_text, executor_output)

        # 构建审查消息
        rules_text = (
            "\n".join(
                f"- [{r['id']}] {r['name']}: {r['description']} (严重度: {r['severity']})"
                for r in rules
            )
            if rules
            else "(无规则)"
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"""## 审查任务

### 原始用户输入
{task.input_text}

### OCR 转写状态: {task.conversion_status}
{"⚠️ 注意：OCR 可能失真，请标注 ocr_risk" if task.conversion_status != "full" else ""}

### 意图路由: {intent}

### 本地预检结果
{json.dumps(local_flags, ensure_ascii=False)}

### 规则库
{rules_text}

### 实干家输出
{executor_output}

请基于以上信息给出审议结论。""",
            },
        ]

        result = self._llm.chat_json(messages)

        if result["ok"]:
            data = result["data"]
            # 合并本地预检结果
            data["local_flags"] = local_flags
            if local_flags["is_invalid"]:
                data["verdict"] = "reject"
                data["rules_triggered"].append("local:rtfm_stfw")

            return AgentResult(
                status="ok",
                output=json.dumps(data, ensure_ascii=False),
                metadata={
                    "verdict": data.get("verdict", "pass"),
                    "rules_triggered": data.get("rules_triggered", []),
                    "ocr_risk": data.get("ocr_risk", False) or task.conversion_status != "full",
                    "comments": data.get("comments", ""),
                    "suggestion": data.get("suggestion", ""),
                },
                next_action="continue",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )
        else:
            return AgentResult(
                status="ok",
                output=result.get("raw", ""),
                metadata={
                    "verdict": "pass",  # 解析失败时放行
                    "rules_triggered": [],
                    "ocr_risk": task.conversion_status != "full",
                    "comments": "审议 JSON 解析失败，默认放行",
                    "parse_error": True,
                },
                next_action="continue",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

    # ------------------------------------------------------------------
    # 本地规则检查（不消耗 LLM）
    # ------------------------------------------------------------------

    def _local_check(self, input_text: str, executor_output: str) -> dict:
        """快速本地规则检查，返回 flags"""
        flags = {
            "is_invalid": False,
            "rtfm_stfw_hit": False,
            "executor_self_reflection": False,
        }

        text_lower = input_text.lower()

        # RTFM/STFW 检测
        rtfm_keywords = [
            "帮我读",
            "帮我查",
            "帮我搜索",
            "帮我搜",
            "read the",
            "search for",
            "look up",
            "rtfm",
            "stfw",
            "google it",
        ]
        if any(kw in text_lower for kw in rtfm_keywords):
            flags["rtfm_stfw_hit"] = True
            flags["is_invalid"] = True

        # 实干家自我反思检测
        reflection_keywords = ["我认为", "我觉得", "我建议", "在我看来", "个人认为"]
        if any(kw in executor_output for kw in reflection_keywords):
            flags["executor_self_reflection"] = True

        return flags
