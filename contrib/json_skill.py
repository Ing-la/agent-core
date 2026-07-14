"""
agent_core.contrib — JSON 文件技能存储

基于 JSON 文件的 SkillProvider 实现。
技能定义格式参见 skills.json.example。
"""

import json
from pathlib import Path
from typing import Optional

from ..skill import Skill
from ..skill_provider import SkillProvider


class JSONFileSkillProvider(SkillProvider):
    """基于 JSON 文件的技能存储实现"""

    def __init__(self, path: str = "skills.json"):
        self.path = Path(path)
        self._skills: dict[str, Skill] | None = None

    def _load(self):
        if self._skills is not None:
            return
        if not self.path.exists():
            self._skills = {}
            return
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self._skills = {}
        for item in data:
            skill = Skill(
                name=item["name"],
                description=item.get("description", ""),
                content=item.get("content", ""),
            )
            self._skills[skill.name] = skill

    async def list_skills(self) -> list[Skill]:
        self._load()
        return list(self._skills.values())

    async def load_skill(self, name: str) -> Optional[Skill]:
        self._load()
        return self._skills.get(name)
