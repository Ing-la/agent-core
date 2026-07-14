"""
MemoryEngine — 记忆编排策略。

负责「何时压缩、何时归档」的策略逻辑，内部调用 MemoryProvider 做存储。
应用层只需实现 MemoryProvider（4 个方法），before_react / after_react 由本类统一提供。
"""

import json
from typing import Any

from .provider import MemoryProvider


class MemoryEngine:
    """
    记忆编排引擎。

    - before_react: 读取长期记忆 + 压缩摘要，合并为 extra_context 注入 system prompt
    - after_react:  存消息 → 检查 token 是否超阈值 → 触发压缩 + 提炼
    """

    COMPRESS_RATIO = 0.7   # prompt_tokens > max_context × 70% 触发压缩
    KEEP_LATEST = 10        # 压缩后保留最近 N 轮完整消息

    def __init__(self, provider: MemoryProvider, llm: Any | None = None):
        self.provider = provider
        self._llm = llm

    # ── 生命周期钩子 ──

    async def before_react(self, user_id: str, conversation_id: str) -> str:
        """Engine.run() 开始时调用：注入长期记忆 + 压缩摘要"""
        # 1. 长期记忆
        keys = await self.provider.list_keys(user_id, prefix="fact:")
        facts = []
        for k in keys:
            data = await self.provider.load(user_id, k)
            if data:
                facts.append(f"  {data.get('key', k)}: {data.get('value', '')}")
        mem_text = "\n".join(facts) if facts else ""

        # 2. 压缩摘要
        summary_data = await self.provider.load(user_id, f"summary:{conversation_id}")

        parts = []
        if mem_text:
            parts.append(f"[用户已知信息]\n{mem_text}")
        if summary_data and summary_data.get("summary"):
            parts.append(f"[对话历史摘要]\n{summary_data['summary']}")
        return "\n\n".join(parts) if parts else ""

    async def after_react(self, user_id: str, conversation_id: str,
                          messages: list, history_start: int,
                          prompt_tokens: int, max_context_tokens: int) -> None:
        """Engine.run() 结束后调用：存消息 → 检查压缩 → 提取"""
        await self._store_turn(user_id, conversation_id, messages, history_start)
        if prompt_tokens > max_context_tokens * self.COMPRESS_RATIO:
            await self._extract(user_id, conversation_id)
            await self._compress(user_id, conversation_id)

    # ── 短期记忆 ──

    async def _store_turn(self, user_id: str, conversation_id: str,
                          messages: list, history_start: int) -> None:
        """本轮消息逐条写入 provider"""
        turn_msgs = messages[history_start:]
        user_count = sum(1 for m in turn_msgs if m["role"] == "user")
        turn_index = user_count
        for msg in turn_msgs:
            await self.provider.save(
                user_id,
                f"msg:{conversation_id}:{turn_index}:{msg['role']}",
                {
                    "role": msg["role"],
                    "content": msg.get("content", ""),
                    "turn_index": turn_index,
                },
            )

    # ── 压缩摘要 ──

    _COMPRESS_SYSTEM_PROMPT = """你是一个对话摘要助手。根据已有摘要和新增对话内容，生成新的完整摘要。

保留以下关键信息：
- 项目名称、单位、人员
- 讨论的决策、结论、时间节点
- 关键数据和指标
- 待办事项和后续计划
- 问题和解决方案"""

    _COMPRESS_USER_PROMPT_TPL = """已有摘要：
{existing_summary}

新增对话内容：
{new_content}

输出 JSON：{{"summary": "新的完整摘要（覆盖已有摘要和新增内容）"}}"""

    async def _compress(self, user_id: str, conversation_id: str) -> None:
        """压缩：读取未压缩消息 → 调 LLM 生成新摘要 → 删除已压缩消息"""
        summary_data = await self.provider.load(user_id, f"summary:{conversation_id}")
        existing_summary = summary_data.get("summary", "") if summary_data else ""

        msg_keys = await self.provider.list_keys(user_id, prefix=f"msg:{conversation_id}:")
        turns: dict[int, list[dict]] = {}
        for k in msg_keys:
            data = await self.provider.load(user_id, k)
            if data:
                ti = data.get("turn_index", 0)
                turns.setdefault(ti, []).append(data)

        if not turns:
            return

        sorted_turns = sorted(turns.items(), key=lambda x: x[0])
        to_compress_turns = sorted_turns[:-self.KEEP_LATEST] if len(sorted_turns) > self.KEEP_LATEST else []
        if not to_compress_turns:
            return

        max_compress_turn = to_compress_turns[-1][0]

        lines = []
        for ti, msgs in to_compress_turns:
            for m in msgs:
                lines.append(f"[{m['role']}]: {m.get('content', '')}")

        text = "\n".join(lines)

        if not self._llm:
            return

        result = await self._llm.chat([
            {"role": "system", "content": self._COMPRESS_SYSTEM_PROMPT},
            {"role": "user", "content": self._COMPRESS_USER_PROMPT_TPL.format(
                existing_summary=existing_summary or "（无）",
                new_content=text,
            )},
        ])

        try:
            parsed = json.loads(result.content)
        except (json.JSONDecodeError, TypeError):
            return

        new_summary = parsed.get("summary", "")
        if new_summary:
            await self.provider.save(user_id, f"summary:{conversation_id}", {
                "summary": new_summary,
                "compressed_through_turn": max_compress_turn,
            })

        # 删除已压缩的原始消息
        for k in msg_keys:
            data = await self.provider.load(user_id, k)
            if data and data.get("turn_index", 0) <= max_compress_turn:
                await self.provider.delete(user_id, k)

    # ── 长期记忆提取 ──

    _EXTRACT_SYSTEM_PROMPT = """从对话内容中提取值得长期记住的用户信息。

关注以下内容：
- 用户的工作角色、职责范围
- 明确表达的个人偏好和习惯
- 用户提到的规则或流程偏好
- 用户的身份特征（如：审批人、项目经理）

注意：
- 只提取跨对话仍有价值的长期信息
- 具体的项目数据、临时任务不提取
- 没有值得记的内容就返回空数组"""

    _EXTRACT_USER_PROMPT_TPL = """对话内容：
{new_content}

输出 JSON 格式，包含一个字段：
user_facts — 数组，每项包含 key（英文标识）、value（事实描述）、category（preference|fact|rule|habit）
示例：
{{"user_facts": [
  {{"key": "prefers_7day_deadline", "value": "用户偏好7天截止期限", "category": "preference"}}
]}}"""

    async def _extract(self, user_id: str, conversation_id: str) -> None:
        """提取：从未压缩消息中识别用户长期记忆并持久化"""
        msg_keys = await self.provider.list_keys(user_id, prefix=f"msg:{conversation_id}:")
        turns: dict[int, list[dict]] = {}
        for k in msg_keys:
            data = await self.provider.load(user_id, k)
            if data:
                ti = data.get("turn_index", 0)
                turns.setdefault(ti, []).append(data)

        if not turns:
            return

        sorted_turns = sorted(turns.items(), key=lambda x: x[0])
        to_extract_turns = sorted_turns[:-self.KEEP_LATEST] if len(sorted_turns) > self.KEEP_LATEST else []
        if not to_extract_turns:
            return

        lines = []
        for ti, msgs in to_extract_turns:
            for m in msgs:
                lines.append(f"[{m['role']}]: {m.get('content', '')}")

        text = "\n".join(lines)

        if not self._llm:
            return

        result = await self._llm.chat([
            {"role": "system", "content": self._EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": self._EXTRACT_USER_PROMPT_TPL.format(new_content=text)},
        ])

        try:
            parsed = json.loads(result.content)
        except (json.JSONDecodeError, TypeError):
            return

        for fact in parsed.get("user_facts", []):
            key = fact.get("key", "")
            if not key:
                continue
            await self.provider.save(user_id, f"fact:{key}", {
                "key": key,
                "value": fact.get("value", ""),
                "category": fact.get("category", "fact"),
                "source_conversation_id": conversation_id,
            })
