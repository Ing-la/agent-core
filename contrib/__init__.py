"""
agent_core — 社区贡献模块

包含开箱即用的默认实现，不污染核心模块。
如果想自定义存储方式，参考这些实现并实现对应的 Provider 接口即可。
"""

from .json_memory import JSONFileMemoryProvider
from .json_skill import JSONFileSkillProvider

__all__ = ["JSONFileMemoryProvider", "JSONFileSkillProvider"]
