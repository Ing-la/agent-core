# 架构设计

## 设计哲学

agent-core 遵循几条核心原则：

1. **极简核心** — 只做 ReAct 循环这一件事，不做编排、不做多 Agent 通信
2. **接口优先** — 所有可替换的部分（LLM / 记忆 / 技能存储）都定义为抽象接口
3. **零假设** — 不假设前端框架、不假设 ORM、不假设部署方式
4. **事件驱动** — Engine 不直接管理 UI，通过事件流让调用方决定怎么展示

---

## 文件职责

### `engine.py` — ReAct 循环调度器

Engine 是系统的核心。它接收 Rule（身份）、tools（工具列表）、LLM（大脑），驱动"思考→行动→观察"循环。

```
用户输入 → [构建 messages] → [调 LLM] ─┬─ 有 tool_call → [执行工具] → 继续循环
                                        └─ 无 tool_call → [返回结果] → 结束
```

关键方法：
- `run()`: 启动一次 ReAct 循环，以 `AsyncGenerator[Event]` 输出事件
- `resume()`: 从 confirm 暂停处恢复执行
- `_react_loop()`: 共享的循环逻辑（run 和 resume 共用）
- `_exec_tools_parallel()`: 独立工具通过 `asyncio.gather` 并发执行
- `_exec_tools_sequential()`: confirm 工具串行执行（需要用户确认）

设计决策：
- **无状态**：Engine 不持有对话历史，每轮 `run()` 是独立的一次循环
- **所有工具全局可见**：不绑定到 Skill 或 Rule，LLM 可直接调用任何工具
- **context 窗口保护**：每轮 LLM 调用前估算 token 数，超限则报错

### `llm.py` — LLM 调用抽象

定义 `LLMProvider` 抽象接口和 OpenAI 兼容协议的默认实现。

- `LLMProvider`：只有 1 个方法 `chat(messages, tools) -> ChatResult`
- `OpenAILLM`：支持重试 + 指数退避、HTTP 代理、OpenAI 兼容 API（vLLM / Ollama 等）

设计决策：
- 抽象只定义 1 个方法，降低自定义 Provider 的成本
- 不引入 `openai` SDK 依赖，用 `httpx` 直接调 API，减少依赖链

### `tool.py` — 工具定义

提供两种定义工具的方式：

- **`Tool` 基类**：继承后实现 `name` / `description` / `parameters` / `execute()`
- **`@tool` 装饰器**：从函数签名自动推断 JSON Schema，自动注册到 `ToolRegistry`

关键设计：
- `ToolRegistry` 是模块级全局 dict，`@tool` 装饰器自动注册
- `inject` 参数支持依赖注入，注入的参数不出现在 LLM 的 JSON Schema 中
- `confirm` / `terminal` 是工具级标记，Engine 根据标记决定执行策略
- `to_openai_format()` 自动生成 OpenAI 兼容的工具定义

### `rule.py` — Agent 身份定义

Rule 是一个简单的 dataclass，包含 `name`、`description`、`system_prompt`。

设计决策：
- Rule 和 Skill 是正交的 — Rule 说"你是谁"，Skill 说"你知道什么"
- `system_prompt` 直接注入到 system message，不做模板处理

### `skill/skill.py` — 领域知识定义

Skill 是一个纯文本 dataclass，包含 `name`、`description`、`content`。

设计决策：
- Skill **不包含**工具定义（与 LangChain 等框架不同）
- 初始只注入技能清单（name + description），完整内容通过 `load_skill` 按需加载

### `skill/provider.py` — 技能存储抽象

两个抽象方法：`list_skills()` 和 `load_skill(name)`。

### `schema.py` — 数据类型定义

零外部依赖的纯 Python dataclass + enum：

- `EventType`：9 种事件类型（thinking / tool_call / tool_result / need_confirm / llm_usage / result / history_trace / done / error）
- `Event`：`type + content` 的通用事件结构
- `ChatResult`：LLM 响应的统一封装（content + tool_calls + usage）
- `ToolCall`：工具调用请求（id + name + arguments）

### `config.py` — LLM 配置

`LLMConfig` dataclass，集中管理 base_url / api_key / model / timeout / max_retries / proxy。提供 `from_dict()` 工厂方法。

### `memory/provider.py` — 记忆存储抽象

4 个原子操作：`save` / `load` / `delete` / `list_keys`。所有方法带 `user_id`，天然用户隔离。

### `memory/engine.py` — 记忆编排引擎

三层记忆策略：

```
before_react() → 注入长期记忆(fact:) + 压缩摘要(summary:)
       ↓
   Engine.run()
       ↓
after_react()  → 存短期消息(msg:) → 检查 token 阈值 → 压缩 + 提取
```

- 压缩：调 LLM 生成对话摘要，删除已压缩的原始消息
- 提取：调 LLM 识别值得长期记住的用户信息，存为 `fact:*`
- 触发条件：`prompt_tokens > max_context_tokens × 0.7`

### `contrib/json_memory.py` — JSON 文件记忆存储

`MemoryProvider` 的 JSON 文件实现，适合原型验证。所有用户数据存于一个 JSON 文件。

### `contrib/json_skill.py` — JSON 文件技能存储

`SkillProvider` 的 JSON 文件实现，从 JSON 文件读取技能定义。

---

## 数据流

```
┌──────────────────────────────────────────────────────────┐
│                       调用方                               │
│  (FastAPI / CLI / 其他 Python 项目)                       │
└──────────┬───────────────────────────────────────────────┘
           │ user_message, history, user_id, conversation_id
           ▼
┌──────────────────────────────────────────────────────────┐
│  Engine.run()                                            │
│                                                          │
│  1. 构建 messages:                                       │
│     - extra_context (来自调用方)                           │
│     - rule.system_prompt                                 │
│     - 可用技能列表 (来自 SkillProvider)                     │
│     - memory context (来自 MemoryEngine.before_react)      │
│     - history (来自调用方 或 MemoryEngine)                 │
│     - user_message                                       │
│                                                          │
│  2. 进入 _react_loop:                                     │
│     ┌──────────────────────┐                             │
│     │ LLM.chat(messages)   │                             │
│     └────────┬─────────────┘                             │
│              │                                            │
│         ┌────┴────┐                                      │
│         │         │                                      │
│   有 tool_call  无 tool_call                              │
│         │         │                                      │
│         ▼         ▼                                      │
│   执行工具      yield result                              │
│   (并行/串行)   yield done                                │
│         │                                                │
│         ▼                                                │
│   结果塞回 messages                                       │
│   继续循环                                                │
│                                                          │
│  yield 事件流:                                            │
│    thinking / tool_call / tool_result /                   │
│    need_confirm / llm_usage / result /                    │
│    history_trace / done / error                          │
└──────────────────────────────────────────────────────────┘
           │ AsyncGenerator[Event]
           ▼
┌──────────────────────────────────────────────────────────┐
│                       调用方                               │
│  根据 event.type 决定展示/处理逻辑                         │
└──────────────────────────────────────────────────────────┘
```

---

## Engine 与 MemoryEngine 的主从关系

初次接触源码时容易产生一种错觉：`before_react → ReAct循环 → after_react` 这个纵向结构看起来像是 MemoryEngine "包裹"了 Engine。但控制权不在 MemoryEngine 手里。

**Engine 是主，MemoryEngine 是宾。** 关系很简单——Engine 在 `run()` 的生命周期里开了两个钩子：

```
Engine.run():
  │
  ├─ before hook:  if memory_engine:
  │                    mem_context = memory_engine.before_react(...)
  │                    messages.insert(mem_context)   ← Engine 主动问，MemoryEngine 给一段文本
  │
  ├─ 核心循环:      _react_loop(...)                  ← Engine 全权控制
  │
  └─ after hook:   if memory_engine:
                       memory_engine.after_react(...)  ← Engine 通知"结束了，你去存吧"
```

关键点：

1. **MemoryEngine 没有控制权** — 它不会主动执行任何操作，Engine 叫它它才动
2. **`before_react()` 只是"要一段文本"** — MemoryEngine 把长期记忆和压缩摘要拼成字符串返回，Engine 把它当做普通的 system message 插入 prompt。Engine 不关心这段文本是怎么来的
3. **`after_react()` 只是"被通知"** — Engine 跑完后说一声，MemoryEngine 自己去存消息、检查阈值、压缩、提取。Engine 不等待这些操作的结果
4. **`memory_engine=None` 时 Engine 完全不变** — 没有任何分支影响核心循环，MemoryEngine 是纯插件

所以从调用关系看是 Engine 握着 `async for` 循环的控制权，MemoryEngine 只是 Engine 生命周期里两个时间点上的回调对象。不是"记忆包裹了 ReAct"，而是"ReAct 在入口和出口各开了一道缝让记忆可以插进来"。

---

## 模块依赖关系

```
engine.py
  ├── llm.py        (LLMProvider / OpenAILLM)
  ├── rule.py       (Rule)
  ├── tool.py       (Tool / ToolRegistry)
  ├── schema.py     (Event / EventType / ChatResult / ToolCall)
  ├── skill/            (Skill / SkillProvider)
  │   ├── skill.py
  │   └── provider.py
  ├── .memory/
  │   ├── provider.py    (MemoryProvider)
  │   └── engine.py      (MemoryEngine)
  └── config.py     (LLMConfig)

contrib/
  ├── json_memory.py     → memory/provider.py
  └── json_skill.py      → skill/provider.py, skill/skill.py
```

所有模块只依赖 `schema.py`（数据类型）和 `config.py`（配置），没有循环依赖。
