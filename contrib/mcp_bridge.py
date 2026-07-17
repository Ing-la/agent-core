"""
agent_core.contrib — MCP Bridge

将 MCP (Model Context Protocol) 服务暴露的工具转换为 agent-core Tool 实例，
Agent 无需知道工具底层是本地函数还是远程 MCP 服务。

只在 `from agent_core.contrib import MCPBridge` 时才需要安装 mcp：
    pip install mcp
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..tool import Tool

if TYPE_CHECKING:
    import mcp


class _MCPTool(Tool):
    """MCP 远程工具的 agent-core 包装器 — 对 Engine 透明，就是普通 Tool"""

    def __init__(self, tool_info: dict, bridge: "MCPBridge"):
        self._name = tool_info["name"]
        self._desc = tool_info.get("description", "")
        # MCP 的 inputSchema 就是 JSON Schema，直接当 parameters 用
        self._params = tool_info.get(
            "inputSchema", {"type": "object", "properties": {}, "required": []}
        )
        self._bridge = bridge

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def parameters(self) -> dict:
        return self._params

    async def execute(self, **kwargs) -> str:
        """实际执行转发到 MCP 服务器"""
        session = self._bridge._session
        result = await session.call_tool(self._name, kwargs)
        if not result.content:
            return ""
        return "\n".join(
            c.text if hasattr(c, "text") else str(c) for c in result.content
        )


class MCPBridge:
    """MCP 协议适配器 — 接外部工具=接本地工具，Engine 无感。

    Usage:
        # 一行连接，工具拿来就用
        bridge = MCPBridge("npx", ["-y", "@anthropic/server-filesystem", "/data"])
        await bridge.connect()
        tools = await bridge.list_tools()  # → list[Tool]

        engine = Engine(llm=llm, rule=rule, tools=[*my_tools, *tools])

        await bridge.close()

        # 也支持 async with
        async with MCPBridge("python", ["my_server.py"]) as bridge:
            tools = await bridge.list_tools()
    """

    def __init__(self, command: str, args: list[str] | None = None):
        self.command = command
        self.args = args or []
        self._session: "mcp.ClientSession | None" = None
        self._cm_read: Any = None
        self._cm_write: Any = None
        self._cm: Any = None

    async def connect(self) -> None:
        """建立到 MCP 服务器的 stdio 连接并初始化会话"""
        try:
            from mcp import ClientSession, StdioServerParameters  # type: ignore[import-untyped]
            from mcp.client.stdio import stdio_client  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError(
                "MCP 适配器需要 mcp 包。执行 pip install mcp 后重试。"
            )

        params = StdioServerParameters(command=self.command, args=self.args)
        self._cm = stdio_client(params)
        self._cm_read, self._cm_write = await self._cm.__aenter__()
        self._session = ClientSession(self._cm_read, self._cm_write)
        await self._session.__aenter__()
        await self._session.initialize()

    async def list_tools(self) -> list[Tool]:
        """列出 MCP 服务端的所有工具，返回 agent-core Tool 实例列表"""
        if not self._session:
            raise RuntimeError("尚未连接 MCP 服务，请先调用 connect()")
        result = await self._session.list_tools()
        tools: list[Tool] = []
        for tc in result.tools:
            info = tc.model_dump() if hasattr(tc, "model_dump") else vars(tc)
            tools.append(_MCPTool(info, self))
        return tools

    async def close(self) -> None:
        """关闭 MCP 连接"""
        if self._session is not None:
            await self._session.__aexit__(None, None, None)
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)

    async def __aenter__(self) -> "MCPBridge":
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
