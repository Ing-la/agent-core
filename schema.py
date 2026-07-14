"""
agent_core — 数据类型定义

零外部依赖，纯 Python dataclass + enum。
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    """ReAct 循环事件类型枚举"""

    THINKING = "thinking"           # LLM 自身的思考文本，content 为 str
    TOOL_CALL = "tool_call"         # 工具调用，content 为 {"name": str, "params": dict}
    TOOL_RESULT = "tool_result"     # 工具返回结果，content 为 {"name": str, "data": str}
    NEED_CONFIRM = "need_confirm"   # 等待用户确认
    LLM_USAGE = "llm_usage"         # token 用量，content 为 {"prompt_tokens": N, "completion_tokens": M}
    RESULT = "result"               # 最终结果，content 可为 str 或 dict
    HISTORY_TRACE = "history_trace" # 本轮完整对话消息列表
    DONE = "done"                   # 循环结束
    ERROR = "error"                 # 错误


@dataclass
class ToolCall:
    """LLM 发起的工具调用请求"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    """LLM 的单次响应"""

    content: str
    tool_calls: list[ToolCall] | None = None
    usage: dict | None = None  # {"prompt_tokens": N, "completion_tokens": M}


@dataclass
class Event:
    """ReAct 循环对外发出的事件"""

    type: EventType
    content: Any
