"""
Agent Cluster CLI 入口
用法:
  python -m agent_cluster.main "用户输入"
  python -m agent_cluster.main --retry task_20260709T143052
  python -m agent_cluster.main --scan
  python -m agent_cluster.main --interactive
  python -m agent_cluster.main --meta-train
"""

import sys
from pathlib import Path

# 确保 agent_cluster 包可导入
_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))


def main():
    args = sys.argv[1:]

    if not args:
        _print_usage()
        return

    first_arg = args[0]

    # --scan
    if first_arg == "--scan":
        _cmd_scan()
        return

    # --retry <task_id>
    if first_arg == "--retry" and len(args) > 1:
        _cmd_retry(args[1])
        return

    # --interactive
    if first_arg == "--interactive":
        _cmd_interactive()
        return

    # --meta-train
    if first_arg == "--meta-train":
        _cmd_meta_train()
        return

    # 默认：完整管道
    user_input = " ".join(args)
    _cmd_run(user_input)


# ------------------------------------------------------------------
# 命令实现
# ------------------------------------------------------------------


def _cmd_run(user_input: str, source_files: list[str] | None = None):
    """完整管道"""
    from agent_cluster.orchestrator import Orchestrator

    orch = Orchestrator()
    result = orch.run(user_input, source_files)
    _print_result(result)


def _cmd_scan():
    """扫描任务"""
    from agent_cluster.task_manager import TaskManager

    tm = TaskManager()
    tasks = tm.scan()
    if not tasks:
        print("📭 task/ 目录暂无任务")
        return

    print(f"📋 共 {len(tasks)} 个任务:\n")
    for t in tasks:
        status_icon = {"full": "🟢", "partial": "🟡", "failed": "🔴"}.get(t.conversion_status, "⚪")
        print(f"  {status_icon} {t.id}")
        print(
            f"     type: {t.type} | files: {len(t.source_files)} | conversion: {t.conversion_status}"
        )
        if t.input_text:
            preview = t.input_text[:80] + ("..." if len(t.input_text) > 80 else "")
            print(f"     input: {preview}")
        print()


def _cmd_retry(task_id: str):
    """重试已有任务"""
    from agent_cluster.orchestrator import Orchestrator

    orch = Orchestrator()
    result = orch.run_existing(task_id)
    if result:
        _print_result(result)


def _cmd_interactive():
    """交互模式"""
    from agent_cluster.orchestrator import Orchestrator

    orch = Orchestrator()
    print("╔══════════════════════════════════╗")
    print("║   Agent Cluster v1.0 交互模式    ║")
    print("║   输入 /quit 退出  /scan 扫描    ║")
    print("╚══════════════════════════════════╝\n")

    while True:
        try:
            line = input("▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Bye.")
            break

        if not line:
            continue
        if line.lower() in ("/quit", "/exit", "/q"):
            print("👋 Bye.")
            break
        if line.lower() == "/scan":
            _cmd_scan()
            continue
        if line.lower() == "/meta":
            _cmd_meta_train()
            continue

        print()
        result = orch.run(line)
        _print_result(result)
        print()


def _cmd_meta_train():
    """元训练"""
    from agent_cluster.orchestrator import Orchestrator

    orch = Orchestrator()
    orch.meta_train()


# ------------------------------------------------------------------
# 工具
# ------------------------------------------------------------------


def _print_result(result):
    """美化输出管道结果"""
    print(f"\n{'='*50}")
    print(result.summary())
    print(f"{'='*50}")
    print(f"\n📝 Executor Output:\n{result.executor_output[:1000]}")
    if len(result.executor_output) > 1000:
        print(f"... (共 {len(result.executor_output)} 字符，已截断)")
    print(f"\n⏱️  总耗时: {result.elapsed_total_ms:.0f}ms")


def _print_usage():
    print("Agent Cluster v1.0")
    print()
    print("用法:")
    print('  python -m agent_cluster.main "<输入>"      完整管道')
    print("  python -m agent_cluster.main --scan           扫描任务")
    print("  python -m agent_cluster.main --retry <id>     重试任务")
    print("  python -m agent_cluster.main --interactive    交互模式")
    print("  python -m agent_cluster.main --meta-train     元训练")


# ------------------------------------------------------------------
# 入口
# ------------------------------------------------------------------

if __name__ == "__main__":
    main()
