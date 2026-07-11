"""
管道编排器 — 将 Guard / Executor / Reviewer 串联为完整流水线

流程：
  1. save_input() → 持久化 + 快照存根
  2. ocr_to_md() → 模糊传递，content.md 永远生成
  3. Guard.process(task) → 仅消费纯文本，意图路由
  4. 按意图分流：
     - analysis  → Executor → Reviewer
     - execution → Executor(+MCP) → Reviewer
     - meta_training → 遍历 archive → Reviewer 批量评估 → 规则增量
  5. 双写归档：archive/ + task/{task_id}/result.json
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .config import config
from .task_manager import TaskManager
from .agents.guard import GuardAgent
from .agents.executor import ExecutorAgent
from .agents.reviewer import ReviewerAgent
from .mcp_client import MCPClient

_TZ = config.timezone


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------


class FinalResult:
    """管道最终输出"""

    def __init__(
        self,
        task_id: str,
        intent: str,
        guard_meta: dict,
        executor_output: str,
        reviewer_meta: dict,
        elapsed_total_ms: float,
    ):
        self.task_id = task_id
        self.intent = intent
        self.guard_meta = guard_meta
        self.executor_output = executor_output
        self.reviewer_meta = reviewer_meta
        self.elapsed_total_ms = elapsed_total_ms

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "intent": self.intent,
            "guard": self.guard_meta,
            "executor_output": self.executor_output,
            "reviewer": self.reviewer_meta,
            "elapsed_total_ms": self.elapsed_total_ms,
            "pipeline": "v1.0",
        }

    def summary(self) -> str:
        verdict = self.reviewer_meta.get("verdict", "?")
        emoji = {"pass": "✅", "reject": "❌", "revise": "🔄"}.get(verdict, "❓")
        return (
            f"{emoji} [{self.task_id}]\n"
            f"   Intent: {self.intent}\n"
            f"   Guard:  {self.guard_meta.get('summary', '?')} (confidence: {self.guard_meta.get('confidence', 0):.2f})\n"
            f"   Review: {verdict} | " + ", ".join(self.reviewer_meta.get("rules_triggered", []))
        )


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------


class Orchestrator:
    """管道编排器"""

    def __init__(self):
        self._task_mgr = TaskManager()
        self._guard = GuardAgent(self._task_mgr._llm)
        self._executor = ExecutorAgent(self._task_mgr._llm)
        self._reviewer = ReviewerAgent(self._task_mgr._llm)
        self._mcp: MCPClient | None = None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self, user_input: str, source_files: list[str] | None = None) -> FinalResult:
        """完整管道：持久化 → OCR → 路由 → 执行 → 审议 → 归档"""
        t0 = time.perf_counter()

        # ---- Step 1: 持久化 ----
        task_id = self._task_mgr.save_input(user_input, source_files)

        # ---- Step 2: OCR ----
        self._task_mgr.ocr_to_md(task_id)

        # ---- Step 3: 加载 Task ----
        task = self._task_mgr.load(task_id)
        if task is None:
            raise RuntimeError(f"Task {task_id} 加载失败")

        # ---- Step 4: Guard 路由 ----
        guard_result = self._guard.process(task)
        intent = guard_result.metadata.get("intent", "analysis")
        print(
            f"\n🚪 Guard: intent={intent}, confidence={guard_result.metadata.get('confidence', 0):.2f}"
        )
        print(f"   {guard_result.metadata.get('summary', '')}")

        # ---- Step 5: 执行 ----
        print(f"\n🔧 Executor ({intent})...")

        # MCP 启动（仅 execution 模式）
        mcp = None
        if intent == "execution" and config.mcp_enabled:
            mcp = self._get_mcp()
            if mcp and not mcp.is_running:
                mcp.start()

        executor_result = self._executor.process(task, intent, mcp_client=mcp)

        # MCP 用后关闭
        if mcp and mcp.is_running:
            mcp.stop()

        # ---- Step 6: 审议 ----
        print(f"\n🔍 Reviewer...")
        reviewer_result = self._reviewer.process(task, executor_result.output, intent)

        # ---- Step 7: 双写归档 ----
        total_elapsed = (time.perf_counter() - t0) * 1000
        final = FinalResult(
            task_id=task_id,
            intent=intent,
            guard_meta=guard_result.metadata,
            executor_output=executor_result.output,
            reviewer_meta=reviewer_result.metadata,
            elapsed_total_ms=total_elapsed,
        )

        self._archive(task, final)

        return final

    def run_existing(self, task_id: str) -> FinalResult | None:
        """对已有任务重新执行管道（重跑 OCR，但跳过持久化）"""
        t0 = time.perf_counter()

        task = self._task_mgr.load(task_id)
        if task is None:
            print(f"Task {task_id} 不存在")
            return None

        # 重新 OCR（文件可能后续补入）
        print(f"\n🔄 Re-OCR for {task_id}...")
        self._task_mgr.ocr_to_md(task_id)
        task = self._task_mgr.load(task_id)
        if task is None:
            raise RuntimeError(f"Task {task_id} 重加载失败")

        # Guard
        guard_result = self._guard.process(task)
        intent = guard_result.metadata.get("intent", "analysis")

        # Executor
        mcp = None
        if intent == "execution" and config.mcp_enabled:
            mcp = self._get_mcp()
            if mcp and not mcp.is_running:
                mcp.start()

        executor_result = self._executor.process(task, intent, mcp_client=mcp)

        if mcp and mcp.is_running:
            mcp.stop()

        # Reviewer
        reviewer_result = self._reviewer.process(task, executor_result.output, intent)

        total_elapsed = (time.perf_counter() - t0) * 1000
        final = FinalResult(
            task_id=task_id,
            intent=intent,
            guard_meta=guard_result.metadata,
            executor_output=executor_result.output,
            reviewer_meta=reviewer_result.metadata,
            elapsed_total_ms=total_elapsed,
        )

        self._archive(task, final)
        return final

    # ------------------------------------------------------------------
    # 元训练
    # ------------------------------------------------------------------

    def meta_train(self) -> FinalResult:
        """遍历 archive 历史 → Reviewer 批量评估 → 规则增量更新（手动确认）"""
        t0 = time.perf_counter()
        archive_dir = config.archive_dir
        cases = sorted(archive_dir.glob("*.json"))

        if not cases:
            return FinalResult("meta_train", "meta_training", {}, "无历史案例", {}, 0)

        reviews = []
        for case_file in cases:
            try:
                case = json.loads(case_file.read_text(encoding="utf-8"))
                # 用 Reviewer 评估历史案例质量
                review = self._llm_chat_json(
                    f"评估以下历史案例的质量（1-10），并判断是否存在 MVP 原则违反：\n{json.dumps(case, ensure_ascii=False)[:3000]}"
                )
                reviews.append({"case": case_file.stem, "review": review})
            except Exception:
                pass

        output = json.dumps(reviews, ensure_ascii=False, indent=2)
        print(f"\n📊 Meta-training: 评估了 {len(reviews)} 个历史案例")
        print(
            f"   结果请查看 archive/meta_train_{datetime.now(_TZ).strftime('%Y%m%dT%H%M%S')}.json"
        )
        print(f"   ⚠️ 规则更新需手动确认后修改 rules/rules.json")

        # 保存评估结果
        meta_file = archive_dir / f"meta_train_{datetime.now(_TZ).strftime('%Y%m%dT%H%M%S')}.json"
        meta_file.write_text(output, encoding="utf-8")

        return FinalResult(
            "meta_train",
            "meta_training",
            {},
            output,
            {"cases_reviewed": len(reviews)},
            (time.perf_counter() - t0) * 1000,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _archive(self, task, final: FinalResult):
        """双写归档"""
        data = final.to_dict()
        data["conversion_status"] = task.conversion_status
        data["archived_at"] = datetime.now(_TZ).isoformat()

        # archive/
        archive_file = config.archive_dir / f"{final.task_id}_result.json"
        archive_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        # task/ 文件夹
        task_result = task.folder_path / "result.json"
        task_result.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_mcp(self) -> MCPClient | None:
        if self._mcp is None and config.mcp_enabled:
            self._mcp = MCPClient()
        return self._mcp

    def _llm_chat_json(self, prompt: str) -> dict:
        """内部 JSON 调用"""
        from .llm_client import LLMClient

        llm = LLMClient()
        return llm.chat_json([{"role": "user", "content": prompt}])
