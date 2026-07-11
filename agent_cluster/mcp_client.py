"""
MCP Client — 简单 stdio 传输
通过 subprocess 调用 MCP Server，JSON-RPC 协议。
MVP 阶段：仅支持 stdio 传输。
"""

import json
import subprocess
import sys
from typing import Any


class MCPClient:
    """最小化 MCP 客户端（stdio 传输）"""

    def __init__(self, server_command: list[str] | None = None):
        """
        server_command: 启动 MCP Server 的命令，如 ["python", "mcp_server.py"]
        """
        from .config import config

        self._command = (
            server_command or config.mcp_server_command.split() if config.mcp_server_command else []
        )
        self._process: subprocess.Popen | None = None
        self._request_id = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """启动 MCP Server 子进程"""
        if not self._command:
            return False
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # 发送 initialize 请求
            self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agent_cluster", "version": "1.0.0"},
                },
            )
            return True
        except Exception:
            return False

    def stop(self):
        """停止 MCP Server"""
        if self._process:
            try:
                self._process.stdin.close()  # type: ignore[union-attr]
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ------------------------------------------------------------------
    # MCP 操作
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        """
        获取可用工具列表。
        返回 OpenAI function calling 兼容格式。
        """
        if not self.is_running:
            return []

        resp = self._send_request("tools/list", {})
        tools = resp.get("tools", [])

        # 转换为 OpenAI function 格式
        openai_tools = []
        for t in tools:
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {}),
                    },
                }
            )
        return openai_tools

    def call_tool(self, name: str, arguments: dict) -> Any:
        """调用 MCP 工具"""
        if not self.is_running:
            raise RuntimeError("MCP Server not running")

        resp = self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        # 提取 content
        content = resp.get("content", [])
        if isinstance(content, list) and content:
            return content[0].get("text", str(content))
        return str(content)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _send_request(self, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求并等待响应"""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        try:
            req_str = json.dumps(request) + "\n"
            self._process.stdin.write(req_str)  # type: ignore[union-attr]
            self._process.stdin.flush()  # type: ignore[union-attr]
            line = self._process.stdout.readline()  # type: ignore[union-attr]
            return json.loads(line).get("result", {})
        except Exception as e:
            print(f"[MCP] RPC error: {e}", file=sys.stderr)
            return {}
