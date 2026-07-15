# API 参考

## agent_core.LLMConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | str | "" | LLM API 地址 |
| `api_key` | str | "" | API 密钥 |
| `model` | str | "" | 模型名称 |
| `timeout` | int | 120 | 请求超时秒数 |
| `max_retries` | int | 0 | 失败重试次数 |
| `proxy` | str or None | None | HTTP 代理地址 |

方法：`classmethod from_dict(d: dict) -> LLMConfig`

---

## agent_core.LLMProvider

抽象方法：`async chat(messages, tools=None) -> ChatResult`

---

## agent_core.OpenAILLM

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | LLMConfig or None | None | 配置对象（优先） |
| `base_url` | str | "" | 向后兼容 |
| `api_key` | str | "" | 向后兼容 |
| `model` | str | "" | 向后兼容 |
| `timeout` | int | 120 | 向后兼容 |

---

## agent_core.Rule

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | 必填 | 角色名称 |
| `description` | str | "" | 一句话描述 |
| `system_prompt` | str | "" | Agent 行为规范 |

---

## agent_core.Tool

| 属性/方法 | 类型 | 说明 |
|----------|------|------|
| `name` | property str | 工具名称 |
| `description` | property str | 工具描述 |
| `parameters` | property dict | JSON Schema |
| `confirm` | property bool | 是否需确认 |
| `terminal` | property bool | 是否终结 |
| `execute(**kwargs)` | async method | 执行工具 |
| `to_openai_format()` | method dict | 转 OpenAI 格式 |

---

## agent_core.tool（装饰器）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str or None | None | 工具名 |
| `description` | str or None | None | 描述 |
| `confirm` | bool | False | 是否需确认 |
| `terminal` | bool | False | 是否终结 |
| `inject` | list[str] or None | None | 注入参数 |

返回 Tool 子类，自动注册到 `ToolRegistry`。

---

## agent_core.Skill

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | 必填 | 技能名称 |
| `description` | str | "" | 技能描述（展示在技能清单中） |
| `content` | str | "" | 技能完整指引文本 |

---

## agent_core.SkillProvider

抽象方法：
- `async list_skills() -> list[Skill]`
- `async load_skill(name: str) -> Skill | None`

---

## agent_core.make_load_skill_tool

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider` | SkillProvider | 技能存储实现 |

创建内置的 `load_skill` 工具供 Agent 按需加载技能。

---

## agent_core.Engine

**构造函数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `llm` | LLMProvider | 必填 | LLM 客户端 |
| `rule` | Rule | 必填 | Agent 身份定义 |
| `tools` | list[Tool] | 必填 | 全局可用工具列表 |
| `skill_provider` | SkillProvider or None | None | 技能存储，开启按需加载 |
| `max_steps` | int | 20 | 最大 ReAct 轮次 |
| `memory_engine` | MemoryEngine or None | None | 记忆引擎 |
| `max_context_tokens` | int | 32768 | 模型最大 context token 数 |

**方法：**

| 方法 | 说明 |
|------|------|
| `run(message, history, extra_context, user_id, conversation_id)` | 启动 ReAct 循环，返回 `AsyncGenerator[Event]` |
| `resume(saved_state)` | 从 confirm 暂停处恢复，返回 `AsyncGenerator[Event]` |

---

## agent_core 数据类

| 类 | 字段 | 说明 |
|----|------|------|
| `EventType` | StrEnum | `THINKING` / `TOOL_CALL` / `TOOL_RESULT` / `NEED_CONFIRM` / `LLM_USAGE` / `RESULT` / `HISTORY_TRACE` / `DONE` / `ERROR` |
| `Event` | `type: EventType`, `content: Any` | 引擎事件 |
| `ChatResult` | `content: str`, `tool_calls: list[ToolCall] or None`, `usage: dict or None` | LLM 响应 |
| `ToolCall` | `id: str`, `name: str`, `arguments: dict` | 工具调用请求 |
