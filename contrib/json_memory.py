"""
agent_core.contrib — JSON 文件记忆存储

基于文件系统的 MemoryProvider 实现，适合原型验证和小规模使用。
生产环境建议替换为数据库实现。
"""

import json
from pathlib import Path
from typing import Optional

from ..memory.provider import MemoryProvider


class JSONFileMemoryProvider(MemoryProvider):
    """基于 JSON 文件的记忆存储实现

    所有用户的记忆存储在一个 JSON 文件中，通过 user_id:key 做隔离。
    """

    def __init__(self, path: str = "memory.json"):
        self.path = Path(path)
        self._cache: dict[str, dict] | None = None

    def _load(self):
        if self._cache is not None:
            return
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self._cache = json.load(f)
        else:
            self._cache = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    async def save(self, user_id: str, key: str, data: dict) -> None:
        self._load()
        self._cache[f"{user_id}:{key}"] = data
        self._save()

    async def load(self, user_id: str, key: str) -> Optional[dict]:
        self._load()
        return self._cache.get(f"{user_id}:{key}")

    async def delete(self, user_id: str, key: str) -> None:
        self._load()
        self._cache.pop(f"{user_id}:{key}", None)
        self._save()

    async def list_keys(self, user_id: str, prefix: str = "") -> list[str]:
        self._load()
        prefix_key = f"{user_id}:{prefix}"
        return [k.split(":", 1)[1] for k in self._cache if k.startswith(prefix_key)]
