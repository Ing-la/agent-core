"""
agent_core — Rule（Agent 身份定义）

Rule 定义 Agent 的身份和行为规范，Engine 将其 system_prompt 注入为 system message。
"""

from dataclasses import dataclass


@dataclass
class Rule:
    """Agent 身份和行为规范定义

    Attributes:
        name: 角色名称，如"数据分析师"
        description: 一句话描述
        system_prompt: 行为规范、工作流程、输出格式
    """

    name: str
    description: str = ""
    system_prompt: str = ""
