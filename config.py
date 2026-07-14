"""
agent_core — LLM 连接配置

集中管理 base_url / api_key / model 等参数，支持 from_dict 工厂方法。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMConfig:
    """LLM API 连接配置"""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 120
    max_retries: int = 0
    proxy: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "LLMConfig":
        return cls(
            base_url=d.get("base_url", ""),
            api_key=d.get("api_key", ""),
            model=d.get("model", ""),
            timeout=d.get("timeout", 120),
            max_retries=d.get("max_retries", 0),
            proxy=d.get("proxy"),
        )
