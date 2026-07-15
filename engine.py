"""
agent_core — ReAct 循环引擎

核心逻辑：
  1. 把 rule（Agent 身份） + skill 清单（可用技能） + 工具定义 + 用户消息发给 LLM
  2. LLM 返回 → 要么是 tool_call，要么是最终回答
  3. 如果是 tool_call → 执行工具 → 结果塞回 messages → 继续
  4. 如果是最终回答 → yield result + done → 结束
  5. Agent 可调用 load_skill(name) 按需加载技能指引文本

所有工具全局可见，不绑定到 Skill。Skill 是纯文本指引，与 Tool 正交。

支持 confirm 模式：工具标记 confirm=True 后不立即执行，
而是 yield need_confirm 等待前端用户确认。

支持并行工具执行：LLM 一次返回多个 tool_calls 时，独立工具通过
asyncio.gather 并发执行（confirm 工具例外，需用户确认）。

Engine 不依赖任何 Web 框架、ORM、数据库，可嵌入任何 Python 项目。
"""

import asyncio
import json
from copy import deepcopy
from typing import Any, AsyncGenerator

from .schema import Event, EventType
from .llm import LLMProvider
from .rule import Rule
from .tool import Tool
from .skill.provider import SkillProvider
from .memory.engine import MemoryEngine

DEFAULT_MAX_STEPS = 20
# 粗略估算：中英文混合按 3 chars/token，作为 context 保护的 guardrail
CHARS_PER_TOKEN = 3


def _estimate_tokens(text: str) -> int:
    """粗略估算字符串的 token 数（不引入 tiktoken 依赖）"""
    return len(text) // CHARS_PER_TOKEN


def _estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的 token 数"""
    total = 0
    for msg in messages:
        for v in msg.values():
            if isinstance(v, str):
                total += _estimate_tokens(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        for sv in item.values():
                            if isinstance(sv, str):
                                total += _estimate_tokens(sv)
    return total


class Engine:
    """ReAct 循环引擎"""

    def __init__(
        self,
        llm: LLMProvider,
        rule: Rule,
        tools: list[Tool],
        skill_provider: SkillProvider | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        memory_engine: MemoryEngine | None = None,
        max_context_tokens: int = 32768,
    ):
        self.llm = llm
        self.rule = rule
        self.tools = tools
        self.skill_provider = skill_provider
        self.max_steps = max_steps
        self.memory_engine = memory_engine
        self.max_context_tokens = max_context_tokens

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        extra_context: str = "",
        user_id: str = "",
        conversation_id: str = "",
    ) -> AsyncGenerator[Event, None]:
        """
        执行一次 ReAct 循环。

        Args:
            user_message: 用户输入
            history: 之前轮次的对话消息（memory 模式下被忽略）
            extra_context: 额外的系统上下文
            user_id: 用户 ID（供 MemoryEngine 使用）
            conversation_id: 对话 ID（供 MemoryEngine 使用）

        Yields:
            Event，含 need_confirm / result / done / error 等
        """
        messages: list[dict[str, Any]] = []

        # 1. 额外上下文
        if extra_context:
            messages.append({"role": "system", "content": extra_context})

        # 2. Rule：Agent 身份和行为规范
        messages.append({"role": "system", "content": self.rule.system_prompt})

        history_start = len(messages)

        # 3. Skill 清单：注入可用技能列表（不注入完整内容）
        if self.skill_provider:
            skills = await self.skill_provider.list_skills()
            if skills:
                skill_lines = [
                    f"- {s.name}：{s.description}" for s in skills if s.description
                ]
                if skill_lines:
                    messages.append({
                        "role": "system",
                        "content": "可用技能：\n" + "\n".join(skill_lines),
                    })
                    history_start += 1

        # 4. MemoryEngine 钩子
        if self.memory_engine:
            self.memory_engine._llm = self.llm
            mem_context = await self.memory_engine.before_react(user_id, conversation_id)
            if mem_context:
                messages.insert(history_start, {
                    "role": "system",
                    "content": mem_context,
                })
                history_start += 1

        # 5. 历史消息
        if self.memory_engine:
            pass  # memory 模式下忽略前端 history
        elif history:
            messages.extend(history)

        # 6. 用户输入
        messages.append({"role": "user", "content": user_message})

        # 所有工具全局可见
        tool_defs = [t.to_openai_format() for t in self.tools]

        last_prompt_tokens = 0
        async for event in self._react_loop(messages, history_start, 0, tool_defs):
            if event.type == EventType.LLM_USAGE:
                last_prompt_tokens = event.content.get("prompt_tokens", 0)
            yield event

        # MemoryEngine 钩子
        if self.memory_engine:
            await self.memory_engine.after_react(
                user_id, conversation_id, messages, history_start,
                prompt_tokens=last_prompt_tokens,
                max_context_tokens=self.max_context_tokens,
            )

    async def resume(self, saved_state: dict) -> AsyncGenerator[Event, None]:
        """从 confirm 暂停处恢复执行"""
        messages = saved_state["messages"]
        history_start = saved_state["history_start"]
        step = saved_state["step"]
        tc_info = saved_state["tool_call"]

        tool = self._find_tool(tc_info["name"])
        if not tool:
            yield Event(EventType.ERROR, f"工具 {tc_info['name']} 已不存在")
            return

        yield Event(EventType.TOOL_CALL, {"name": tool.name, "params": tc_info["arguments"]})
        try:
            result = await tool.execute(**deepcopy(tc_info["arguments"]))
        except Exception as e:
            result = f"执行出错：{e}"

        yield Event(EventType.TOOL_RESULT, {"name": tool.name, "data": result})

        messages.append({
            "role": "tool",
            "tool_call_id": tc_info["id"],
            "content": result,
            "name": tc_info["name"],
        })

        if getattr(tool, "terminal", False):
            try:
                parsed = json.loads(result)
                yield Event(EventType.RESULT, parsed)
            except (json.JSONDecodeError, TypeError):
                yield Event(EventType.RESULT, result or "（已提交）")
            yield Event(EventType.HISTORY_TRACE, messages[history_start:])
            yield Event(EventType.DONE, "")
            return

        tool_defs = [t.to_openai_format() for t in self.tools]
        async for event in self._react_loop(messages, history_start, step + 1, tool_defs):
            yield event

    # ── 内部：ReAct 循环 ──

    async def _react_loop(
        self,
        messages: list[dict[str, Any]],
        history_start: int,
        start_step: int,
        tool_defs: list[dict],
    ) -> AsyncGenerator[Event, None]:
        """共享的 ReAct 循环逻辑"""
        for step in range(start_step, self.max_steps):
            # 上下文窗口保护：估算 token 数，超过限制则报错
            if _estimate_messages_tokens(messages) > self.max_context_tokens:
                yield Event(EventType.HISTORY_TRACE, messages[history_start:])
                yield Event(EventType.ERROR, "对话上下文超过模型最大长度限制，请重新开始。")
                return

            response = await self.llm.chat(messages, tool_defs)

            if response.usage:
                yield Event(EventType.LLM_USAGE, response.usage)

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
            }
            if response.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in response.tool_calls
                ]
            messages.append(assistant_msg)

            # ── 有工具调用 ──
            if response.tool_calls:
                if response.content.strip():
                    yield Event(EventType.THINKING, response.content.strip())

                # 检查是否有 confirm 工具（必须串行，不能并行）
                has_confirm = any(
                    getattr(self._find_tool(tc.name), "confirm", False)
                    for tc in response.tool_calls
                )

                if has_confirm:
                    sub_gen = self._exec_tools_sequential(
                        messages, history_start, step, response.tool_calls,
                    )
                else:
                    sub_gen = self._exec_tools_parallel(
                        messages, history_start, response.tool_calls,
                    )

                last_type = None
                async for event in sub_gen:
                    yield event
                    last_type = event.type

                # 子生成器已发出 DONE 或 NEED_CONFIRM → 结束循环
                if last_type in (EventType.DONE, EventType.NEED_CONFIRM):
                    return
                continue

            # ── 没有工具调用 → 最终回答 ──
            yield Event(EventType.RESULT, response.content.strip() or "（无回复）")
            yield Event(EventType.HISTORY_TRACE, messages[history_start:])
            yield Event(EventType.DONE, "")
            return

        # 超出最大步数
        yield Event(EventType.HISTORY_TRACE, messages[history_start:])
        yield Event(EventType.ERROR, f"对话超过 {self.max_steps} 步限制，请重新开始。")

    async def _exec_tools_sequential(
        self,
        messages: list[dict[str, Any]],
        history_start: int,
        step: int,
        tool_calls: list,
    ) -> AsyncGenerator[Event, None]:
        """串行执行工具（confirm 工具路径）"""
        for tc in tool_calls:
            tool = self._find_tool(tc.name)
            if not tool:
                yield Event(EventType.TOOL_CALL, {"name": tc.name, "params": tc.arguments})
                yield Event(EventType.TOOL_RESULT, {"name": tc.name, "data": "错误：未知工具"})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"错误：没有名为 {tc.name} 的工具",
                    "name": tc.name,
                })
                continue

            yield Event(EventType.TOOL_CALL, {"name": tool.name, "params": tc.arguments})

            # 需要用户确认 → 暂停
            if getattr(tool, "confirm", False):
                state = {
                    "messages": messages,
                    "history_start": history_start,
                    "step": step,
                    "tool_call": {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                conversation = messages[history_start:-1]
                yield Event(EventType.HISTORY_TRACE, conversation)
                yield Event(EventType.NEED_CONFIRM, state)
                return

            # 执行工具
            try:
                result = await tool.execute(**tc.arguments)
            except Exception as e:
                result = f"执行出错：{e}"

            yield Event(EventType.TOOL_RESULT, {"name": tool.name, "data": result})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
                "name": tc.name,
            })

            if getattr(tool, "terminal", False):
                try:
                    parsed = json.loads(result)
                    yield Event(EventType.RESULT, parsed)
                except (json.JSONDecodeError, TypeError):
                    yield Event(EventType.RESULT, result or "（已提交）")
                yield Event(EventType.HISTORY_TRACE, messages[history_start:])
                yield Event(EventType.DONE, "")
                return

    async def _exec_tools_parallel(
        self,
        messages: list[dict[str, Any]],
        history_start: int,
        tool_calls: list,
    ) -> AsyncGenerator[Event, None]:
        """并行执行独立工具"""
        # 先发出所有 TOOL_CALL 事件
        validated: list[tuple[Any, Any]] = []  # (tool, tc)
        for tc in tool_calls:
            tool = self._find_tool(tc.name)
            if tool:
                yield Event(EventType.TOOL_CALL, {"name": tool.name, "params": tc.arguments})
                validated.append((tool, tc))
            else:
                yield Event(EventType.TOOL_CALL, {"name": tc.name, "params": tc.arguments})
                yield Event(EventType.TOOL_RESULT, {"name": tc.name, "data": "错误：未知工具"})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"错误：没有名为 {tc.name} 的工具",
                    "name": tc.name,
                })

        if not validated:
            return

        # 并行执行
        async def _exec_one(tool: Tool, tc: Any) -> tuple[Any, str]:
            try:
                r = await tool.execute(**tc.arguments)
            except Exception as e:
                r = f"执行出错：{e}"
            return tc, r

        results = await asyncio.gather(*[_exec_one(t, tc) for t, tc in validated])

        # 发出 TOOL_RESULT 事件并追加到 messages
        has_terminal = False
        terminal_result = ""
        terminal_name = ""

        for tc, result in results:
            tool = self._find_tool(tc.name)
            yield Event(EventType.TOOL_RESULT, {"name": tool.name, "data": result})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
                "name": tc.name,
            })

            if getattr(tool, "terminal", False):
                has_terminal = True
                terminal_result = result
                terminal_name = tool.name

        # 如果有终结工具，处理其结果
        if has_terminal:
            try:
                parsed = json.loads(terminal_result)
                yield Event(EventType.RESULT, parsed)
            except (json.JSONDecodeError, TypeError):
                yield Event(EventType.RESULT, terminal_result or "（已提交）")
            yield Event(EventType.HISTORY_TRACE, messages[history_start:])
            yield Event(EventType.DONE, "")

    # ── 内部辅助 ──

    def _find_tool(self, name: str) -> Any | None:
        return next((t for t in self.tools if t.name == name), None)
