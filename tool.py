"""
agent_core — 工具抽象基类 + @tool 装饰器

定义 Tool 接口和 ToolRegistry，业务模块可以继承 Tool 基类
或使用 @tool 装饰器快速定义工具。
"""

import inspect
import typing
from abc import ABC, abstractmethod
from typing import Any, Optional, get_type_hints


# ── 全局工具注册表 ──

ToolRegistry: dict[str, type["Tool"]] = {}

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


def _json_type(t: Any) -> str:
    """从 Python 类型标注推断 JSON Schema type。"""
    origin = getattr(t, "__origin__", t)
    if origin in _TYPE_MAP:
        return _TYPE_MAP[origin]
    if origin is typing.Union:
        args = getattr(t, "__args__", [])
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return _json_type(non_none[0])
    return "string"


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    confirm: bool = False,
    terminal: bool = False,
    inject: Optional[list[str]] = None,
):
    """
    装饰器：将函数转为 Tool 子类，并自动注册到 ToolRegistry。

    Args:
        name: 工具名（默认用函数名）
        description: 描述（默认用函数 docstring）
        confirm: 是否需用户确认
        terminal: 是否终结型工具
        inject: 需要注入的参数名列表，这些参数不会出现在 LLM 的 JSON Schema 中

    Usage:
        @tool()
        def query_project(project_name: str):
            \"\"\"查询工程信息\"\"\"
            return db.query(...)

        # 使用：注入依赖后得到实例
        instance = query_project(db=session)
        await instance.execute(project_name="某工程")

        # 注册表也可访问
        ToolRegistry["query_project"]  # → <class DecoratedTool>
    """
    _inject = inject or []

    def decorator(func):
        sig = inspect.signature(func)

        # 生成 JSON Schema
        properties = {}
        required = []
        try:
            hints = get_type_hints(func)
        except Exception:
            hints = {}

        for pname, p in sig.parameters.items():
            if pname in _inject:
                continue
            ptype = hints.get(pname, str)
            properties[pname] = {
                "type": _json_type(ptype),
                "description": "",
            }
            if p.default is inspect.Parameter.empty:
                required.append(pname)

        desc = description or (func.__doc__ and func.__doc__.strip()) or func.__name__

        # 判断 func 是 async 还是 sync
        is_async = inspect.iscoroutinefunction(func)

        tool_name = name or func.__name__

        class DecoratedTool(Tool):
            name = tool_name
            description = desc
            _confirm = confirm
            _terminal = terminal
            parameters = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

            def __init__(self, **injected):
                self.injected = injected

            async def execute(self, **kwargs):
                merged = {**self.injected, **kwargs}
                if is_async:
                    return await func(**merged)
                return func(**merged)

        DecoratedTool.__name__ = func.__name__
        DecoratedTool.__qualname__ = func.__qualname__

        ToolRegistry[DecoratedTool.name] = DecoratedTool
        return DecoratedTool

    return decorator


# ── 工具基类（保留原有方式） ──


class Tool(ABC):
    """
    工具基类。

    子类只需实现 name / description / parameters 三个属性
    和 execute() 方法，to_openai_format() 自动生成 OpenAI 兼容的工具定义。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        ...

    @property
    def terminal(self) -> bool:
        return False

    @property
    def confirm(self) -> bool:
        return False

    def to_openai_format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── 内置工具工厂 ──


def make_load_skill_tool(provider) -> Tool:
    """
    创建 load_skill 内置工具，供 Agent 按需加载技能指引。

    加载后技能内容以文本形式注入对话上下文，不修改工具列表。
    所有工具始终全局可见。

    Usage:
        provider = JsonSkillProvider("skills/")
        skill_tool = make_load_skill_tool(provider)
        engine = Engine(llm=llm, rule=rule, tools=[*other_tools, skill_tool], ...)
    """
    from .skill_provider import SkillProvider

    @tool(
        name="load_skill",
        description=(
            "加载某个技能的详细指引。当你需要特定领域的专业知识（如标注规则、"
            "分析流程、注意事项等）时，调用此工具按名称加载。系统中有可用技能列表，"
            "你可以参考那个列表决定加载哪个。"
        ),
        inject=["_provider"],
    )
    async def load_skill(_provider: SkillProvider, name: str) -> str:  # noqa: F821
        """按名称加载技能指引

        Args:
            name: 技能名称，从系统提示词中的"可用技能"列表中选择
        Returns:
            技能的完整指引文本
        """
        skill = await _provider.load_skill(name)
        if not skill:
            return f"未找到名为「{name}」的技能。"
        return skill.content

    instance = load_skill(_provider=provider)
    return instance
