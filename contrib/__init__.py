"""
agent_core — 扩展（插件）

可选的默认实现与适配器，与核心解耦。
只在业务代码中按需 import，不 import 其代码不会进进程。

包含：
- JSONFileMemoryProvider  — 基于 JSON 文件的记忆存储
- JSONFileSkillProvider   — 基于 JSON 文件的技能存储
- MCPBridge               — 将 MCP 外部工具转为 agent-core Tool 实例
"""

from .json_memory import JSONFileMemoryProvider
from .json_skill import JSONFileSkillProvider
from .mcp_bridge import MCPBridge

__all__ = ["JSONFileMemoryProvider", "JSONFileSkillProvider", "MCPBridge"]
