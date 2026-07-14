from abc import ABC, abstractmethod
from typing import Any, Optional


class MemoryProvider(ABC):
    """
    记忆存储抽象接口——只规定「存、取、删、列」四个原子操作。
    「何时存、何时压缩、何时提取」等编排策略由 MemoryEngine 负责。
    """

    @abstractmethod
    async def save(self, user_id: str, key: str, data: dict) -> None:
        """保存一条记忆"""
        ...

    @abstractmethod
    async def load(self, user_id: str, key: str) -> Optional[dict]:
        """读取一条记忆，不存在返回 None"""
        ...

    @abstractmethod
    async def delete(self, user_id: str, key: str) -> None:
        """删除一条记忆"""
        ...

    @abstractmethod
    async def list_keys(self, user_id: str, prefix: str = "") -> list[str]:
        """列出某用户所有匹配前缀的记忆 key"""
        ...
