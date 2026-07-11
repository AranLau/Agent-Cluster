"""
集中配置模块
从环境变量/.env 读取配置，提供合理的默认值。
可迁移至 MAXKB/CLAW 时只需调整此文件。
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

# 项目根目录 = agent_cluster/ 的父目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str = "") -> str:
    """读取环境变量，优先 .env 文件"""
    # 尝试从 .env 文件加载
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key and k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
    return os.environ.get(key, default)


@dataclass
class Config:
    """Agent Cluster 全局配置"""

    # --- LLM ---
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "http://localhost:11434/v1")
    )
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "ollama"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "qwen2.5:7b"))
    llm_temperature: float = 0.3

    # --- MCP ---
    mcp_enabled: bool = field(
        default_factory=lambda: _env("MCP_ENABLED", "false").lower() == "true"
    )
    mcp_server_command: str = field(default_factory=lambda: _env("MCP_SERVER_COMMAND", ""))

    # --- OCR（独立的翻译层，不依赖 Agent LLM） ---
    paddleocr_api_url: str = field(default_factory=lambda: _env("PADDLEOCR_API_URL", ""))
    paddleocr_api_key: str = field(default_factory=lambda: _env("PADDLEOCR_API_KEY", ""))

    # --- 路径 ---
    task_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "task")
    archive_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "archive")
    rules_path: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "rules" / "rules.json"
    )

    # --- 管道 ---
    max_review_retries: int = 1  # 审议 revise 后的重试次数 (V1.0=1, 后续支持回路)

    # --- 时区 ---
    timezone_offset: int = field(
        default_factory=lambda: int(_env("TZ_OFFSET", "8"))
    )  # UTC 偏移量，默认 +8（北京时间）

    @property
    def timezone(self):
        """返回 timezone 对象"""
        return __import__("datetime").timezone(
            __import__("datetime").timedelta(hours=self.timezone_offset)
        )

    def as_dict(self) -> dict:
        """用于日志输出（隐藏 API key）"""
        d = {k: str(v) for k, v in self.__dict__.items()}
        d["llm_api_key"] = "***" if self.llm_api_key else "(not set)"
        return d


# 全局单例
config = Config()
