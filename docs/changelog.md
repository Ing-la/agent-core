# 变更记录

### v0.4.0 (2026-07-13)

- **Rule 新增** — 引入 `Rule` 数据类，定义 Agent 身份和行为规范，替代原来 `Skill` 中的 `system_prompt`
- **Skill 重构** — 去掉 `system_prompt` 和 `tools` 字段，改为纯文本领域知识指引（`name` + `description` + `content`）
- **SkillProvider 新增** — 技能存储抽象接口（`list_skills` / `load_skill`），与 `MemoryProvider` pattern 一致
- **`load_skill` 内置工具** — 通过 `make_load_skill_tool()` 工厂创建，Agent 运行时按需加载技能
- **Tool 全局可见** — 所有工具直接传入 Engine，不再绑定到 Skill，不依赖 Skill 加载即可调用
- **LLMProvider 抽象化** — 提取 `LLMProvider` 抽象基类，原有实现改为 `OpenAILLM(LLMProvider)`
- **EventType 枚举** — `Event.type` 从 `str` 改为 `EventType` StrEnum
- **Engine 重构** — 构造函数签名改为 `(llm, rule, tools, ...)`，system prompt 从 `rule.system_prompt` 生成

### v0.3.0 (2026-07-09)

- 新增 `MemoryProvider` 抽象接口（save/load/delete/list_keys），记忆存储与编排策略解耦
- 新增 `MemoryEngine` 记忆编排引擎（before_react / after_react / _compress / _extract），实现三层记忆
- `ChatResult` 新增 `usage` 字段
- `Engine.__init__` 新增 `memory_engine` 和 `max_context_tokens` 参数
- `Engine.run()` 新增 `user_id` 和 `conversation_id` 参数
- 新增 `llm_usage` 事件类型
- 新增 `LLMConfig` 配置类、`@tool` 装饰器、`ToolRegistry` 全局注册表

### v0.1.0

- 初始版本：Engine / LLM / Tool / Skill / Event / ChatResult / ToolCall
