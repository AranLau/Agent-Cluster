"""
MCP Server 入口 — 将 Agent Cluster 管道暴露为 MCP Tool。

在 openclaw / Claude Desktop 等 MCP Host 中配置：
{
  "agent-cluster": {
    "command": "python",
    "args": ["-m", "agent_cluster.mcp_server"]
  }
}

暴露的 tool：
  run_pipeline(input_text: str, file_paths: list[str]) → 完整管道结果 (JSON)
"""

import json
import sys
from pathlib import Path

# 确保 agent_cluster 可导入
_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

STDIN = sys.stdin
STDOUT = sys.stdout


def _send(response: dict) -> None:
    STDOUT.write(json.dumps(response, ensure_ascii=False) + "\n")
    STDOUT.flush()


def handle_request(req: dict) -> dict:
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agent-cluster", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "run_pipeline",
                        "description": "通过 Agent Cluster 三段式管道（路由→执行→审议）处理用户输入。支持文件分析、报告生成、规则审议。",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "input_text": {
                                    "type": "string",
                                    "description": "用户的输入文本或指令",
                                },
                                "file_paths": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "需要处理的文件绝对路径列表（可选）",
                                },
                            },
                            "required": ["input_text"],
                        },
                    }
                ]
            },
        }

    if method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "run_pipeline":
            from agent_cluster.orchestrator import Orchestrator

            orch = Orchestrator()
            input_text = arguments.get("input_text", "")
            file_paths = arguments.get("file_paths")
            result = orch.run(input_text, file_paths)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                        }
                    ]
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main() -> None:
    for line in STDIN:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            _send(resp)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
        except Exception as e:
            _send({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    main()
