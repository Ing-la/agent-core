"""
agent_core — SkillProvider（技能存储抽象接口）

业务层实现此接口来提供技能存储（文件 JSON / 数据库 / 远程 API）。
框架不关心存储方式。
"""

from abc import ABC, abstractmethod
from typing import Optional

from .skill import Skill


class SkillProvider(ABC):
    """技能存储抽象接口"""

    @abstractmethod
    async def list_skills(self) -> list[Skill]:
        """列出所有可用技能"""
        ...

    @abstractmethod
    async def load_skill(self, name: str) -> Optional[Skill]:
        """按名称加载技能详情，不存在返回 None"""
        ...
