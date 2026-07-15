"""
agent_core — Skill（技能）

Skill 是纯文本的领域知识/流程指引，按需加载后以文本形式注入对话上下文。
与 Tool 正交——Skill 不包含工具定义，工具始终全局可见。
"""

from dataclasses import dataclass


@dataclass
class Skill:
    """
    领域技能定义（纯文本指引）。

    Attributes:
        name: 技能名称，如"河流标注规则"
        description: 一句话描述，展示在技能清单中供 Agent 按需选用
        content: 完整的知识/流程/规范正文，调用 load_skill 时注入
    """

    name: str
    description: str = ""
    content: str = ""
