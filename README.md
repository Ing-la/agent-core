# agent-core

轻量级 AI Agent 内核引擎，驱动 ReAct（思考-行动-观察）循环。

**零非必要依赖**（仅 `httpx`），可嵌入任何 Python 项目。

---

## 安装

```bash
# 直接 pip 安装（需要 git）
pip install git+https://github.com/Ing-la/agent-core.git

# 或复制 agent_core/ 目录到项目中使用（零依赖部署）
```

## 快速开始

```python
import asyncio
from agent_core import OpenAILLM, LLMConfig, Rule, Engine, Tool
from agent_core import tool


# 方式一：继承 Tool 基类
class QueryTime(Tool):
    name = "query_time"
    description = "查询当前时间"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 方式二：@tool 装饰器（推荐）
@tool(description="查询当前日期")
def query_date():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


# 创建 LLM、Rule、工具列表
llm = OpenAILLM(config=LLMConfig(
    base_url="http://localhost:8000/v1",
    api_key="sk-xxx",
    model="Qwen2.5-14B-Instruct",
))

rule = Rule(
    name="助手",
    description="通用 AI 助手",
    system_prompt="你是一个有用的助手，可以调用工具来解答用户问题。",
)

tools = [QueryTime(), query_date()]

# 运行 Engine
engine = Engine(llm=llm, rule=rule, tools=tools)

async def main():
    async for event in engine.run("现在几点了？"):
        match event.type:
            case "result":      print(f"回答：{event.content}")
            case "thinking":    print(f"思考：{event.content}")
            case "tool_call":   print(f"调用：{event.content}")
            case "tool_result": print(f"结果：{event.content}")
            case "done":        print("完成")
            case "error":       print(f"错误：{event.content}")

asyncio.run(main())
```

---

## 核心概念

### Tool

工具是 LLM 与外部世界交互的接口。每个工具需定义名称、描述、参数结构和执行逻辑。**所有工具全局可见**，不绑定到任何 Skill 或 Rule。

```python
from agent_core import Tool

class MyTool(Tool):
    name = "tool_name"                    # LLM 通过此名称调用
    description = "这个工具做什么的"        # LLM 判断何时调用的依据
    parameters = {                         # JSON Schema 格式的参数定义
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "参数说明"},
        },
        "required": ["param1"],
    }
    confirm = False    # 为 True 时执行前需用户确认
    terminal = False   # 为 True 时执行后结束 ReAct 循环

    async def execute(self, param1: str) -> str:
        """执行工具，返回文本结果"""
        return f"处理了 {param1}"
```

### @tool 装饰器

装饰器方式自动处理上面的大部分样板代码。

```python
@tool(
    name=None,          # 工具名，默认用函数名
    description=None,   # 描述，默认用函数 docstring
    confirm=False,      # 是否需用户确认
    terminal=False,     # 是否终结型工具
    inject=None,        # 注入参数名列表，如 ["db"]
)
def my_tool(param1: str, param2: int = 0):
    """函数文档字符串会被自动提取为 description"""
    ...

# 使用
instance = my_tool(db=some_session)   # 传入注入的依赖
await instance.execute(param1="hello")  # LLM 调用时只传业务参数
```

### Rule

Rule 定义 Agent 的身份和行为规范，Engine 将其 `system_prompt` 注入为 system message。

```python
from agent_core import Rule

rule = Rule(
    name="数据分析师",
    description="擅长数据分析和可视化",
    system_prompt="你是一位数据分析师。按需求分析数据、生成图表，给出专业建议。",
)
```

Rule 和 Skill 是正交关系。Rule 决定了"你是谁"，Skill 提供了"你该领域的专业知识"。

### Skill

Skill 是纯文本的领域知识/流程指引。与 Tool **正交**——Skill **不包含**工具定义。

```python
from agent_core import Skill

skill = Skill(
    name="河流标注规则",
    description="电力线路跨河选线标注的专业知识",
    content="""跨河选线核心原则：
- 交角以接近 0° 或小于 5° 为佳，不超过 30°
- 塔位应选在河道狭窄、河岸稳定处
- 避开码头和泊船地区""",
)
```

Agent 初始状态 system prompt 只注入技能列表（name + description），完整内容通过 `load_skill` 工具按需加载。即使不加载任何 Skill，Agent 也能正常调用全局工具。

### SkillProvider

技能存储的抽象接口。业务层实现 `list_skills()` 和 `load_skill()` 两个方法（文件 JSON / 数据库 / 远程 API）。

```python
from agent_core import SkillProvider, Skill

class JsonSkillProvider(SkillProvider):
    async def list_skills(self) -> list[Skill]:
        # 从 JSON 文件读取
        ...

    async def load_skill(self, name: str) -> Skill | None:
        # 按名称查找技能
        ...
```

agent_core 内置 `make_load_skill_tool(provider)` 工厂函数，创建一个 `load_skill` 工具让 Agent 在运行时按需加载 Skill：

```python
from agent_core import make_load_skill_tool

provider = JsonSkillProvider("skills/")
skill_tool = make_load_skill_tool(provider)
engine = Engine(llm=llm, rule=rule, tools=[*other_tools, skill_tool], skill_provider=provider)
```

`load_skill` 只注入文本到对话上下文，不修改工具列表。

### LLMConfig

集中管理 LLM API 连接参数。

```python
from agent_core import LLMConfig

# 直接构造
cfg = LLMConfig(
    base_url="http://192.168.1.100:8000/v1",
    api_key="sk-xxx",
    model="Qwen2.5-14B-Instruct",
    timeout=120,
)

# 从字典构造
cfg = LLMConfig.from_dict({
    "base_url": "http://192.168.1.100:8000/v1",
    "api_key": "sk-xxx",
    "model": "Qwen2.5-14B-Instruct",
})
```

### LLMProvider / OpenAILLM

LLM 调用抽象接口，与 `MemoryProvider` / `SkillProvider` 保持一致 pattern。

```python
from agent_core import LLMProvider, OpenAILLM

# 使用内置 OpenAI 兼容实现
llm = OpenAILLM(config=LLMConfig(base_url="...", api_key="...", model="..."))

# 或实现自定义 Provider
class AnthropicLLM(LLMProvider):
    async def chat(self, messages, tools=None):
        # 对接 Anthropic SDK
        ...
```

### contrib — 开箱即用的默认实现

```python
from agent_core.contrib import JSONFileMemoryProvider, JSONFileSkillProvider

# 基于 JSON 文件的记忆存储
memory = JSONFileMemoryProvider("memory.json")

# 基于 JSON 文件的技能存储
skills = JSONFileSkillProvider("skills.json")
```

### Engine

Engine 驱动 ReAct 循环，是核心调度器。

```python
engine = Engine(llm=llm, rule=rule, tools=tools, max_steps=15)

# 启动新对话
async for event in engine.run("用户消息", history=None, extra_context="")：

# 恢复被 confirm 暂停的对话
async for event in engine.resume(saved_state):
    ...
```

Engine 不依赖任何 Web 框架、ORM、数据库，可嵌入任何 Python 项目。

#### ReAct 循环流程

```
Engine.__init__(llm, rule, tools, skill_provider=None, ...)

run(user_message):
  1. 构建 messages:
     - extra_context
     - rule.system_prompt                    ← Agent 身份
     - 可用技能列表（name + description）      ← 如果提供 skill_provider
     - memory context（如果启用 MemoryEngine）
     - history
     - user_message
  2. tool_defs = [t.to_openai_format() for t in tools] ← 所有工具全局可见
  3. _react_loop:
     - LLM.chat(messages, tool_defs)
     - 有 tool_call → 执行 → 继续
     - 无 tool_call → yield result → done
  4. Agent 随时可调用 load_skill("XXX")：
     - skill.content 以文本形式返回并注入上下文
     - tool_defs 不变（工具本来就全局可见）
     - LLM 获得领域指引后更准确地调用工具
```

### Event

Engine 以异步生成器 `AsyncGenerator[Event]` 对外输出。

```python
from agent_core import Event, EventType

@dataclass
class Event:
    type: EventType    # 枚举值，见下表
    content: Any
```

---

### MemoryProvider

记忆存储抽象接口，只规定 4 个原子操作：

| 方法 | 说明 |
|------|------|
| `save(user_id, key, data)` | 保存一条记忆（UPSERT） |
| `load(user_id, key)` | 读取一条记忆，不存在返回 None |
| `delete(user_id, key)` | 删除一条记忆 |
| `list_keys(user_id, prefix)` | 列出某用户所有匹配前缀的 key |

所有方法都带 `user_id`，实现类通过 `WHERE user_id = ? AND key = ?` 做用户隔离。

### MemoryEngine

记忆编排引擎，负责"何时压缩、何时提取"的策略逻辑，内部调用 MemoryProvider 做存储、LLM 做压缩/提取。

```python
from agent_core.memory import MemoryProvider, MemoryEngine

provider = SqliteMemory()  # 业务层实现
memory_engine = MemoryEngine(provider=provider, llm=llm)
engine = Engine(llm=llm, rule=rule, tools=tools, memory_engine=memory_engine)
```

**三层记忆：**

| 层次 | key 前缀 | 写入者 | 读取者 |
|------|---------|--------|--------|
| 短期记忆 | `msg:{conv_id}:{turn}:{role}` | `_store_turn()`（每轮） | 压缩/提取时读取 |
| 压缩记忆 | `summary:{conv_id}` | `_compress()`（token > 70% 触发） | 每次 `before_react()` |
| 长期记忆 | `fact:{key}` | `_extract()`（与压缩同触发） | 每次 `before_react()` |

---

## SSE 事件协议

| 事件类型 | EventType 枚举 | content 类型 | 产生时机 | 消费方 |
|---------|---------------|-------------|---------|--------|
| `thinking` | `EventType.THINKING` | str | LLM 返回了思考文本 | 前端展示思考过程 |
| `tool_call` | `EventType.TOOL_CALL` | `{name, params}` | LLM 发起工具调用 | 前端显示"执行中"卡片 |
| `tool_result` | `EventType.TOOL_RESULT` | `{name, data}` | 工具执行完毕 | 前端更新卡片状态 |
| `need_confirm` | `EventType.NEED_CONFIRM` | dict（引擎状态） | 遇到 confirm=True 的工具 | 前端弹出确认/取消 |
| `llm_usage` | `EventType.LLM_USAGE` | `{prompt_tokens, completion_tokens}` | 每次 LLM 调用后 | Engine 记录 token 用量 |
| `result` | `EventType.RESULT` | str 或 dict | 最终回答 | 前端显示对话气泡 |
| `history_trace` | `EventType.HISTORY_TRACE` | list[dict] | 每轮结束或 confirm 暂停时 | 前端替换本地历史 |
| `done` | `EventType.DONE` | "" | 正常结束 | 前端关闭 SSE 流 |
| `error` | `EventType.ERROR` | str | LLM 调用失败 / 工具不存在 / 超步 | 前端展示错误信息 |

---

## 集成指南

### FastAPI SSE 接入

```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from agent_core import OpenAILLM, LLMConfig, Rule, Engine, make_load_skill_tool
import json

router = APIRouter()

@router.post("/chat/stream")
async def chat_stream():
    llm = OpenAILLM(config=LLMConfig(base_url="...", model="..."))
    rule = Rule(name="助手", system_prompt="...")
    engine = Engine(llm=llm, rule=rule, tools=[...])

    async def generate():
        async for event in engine.run("用户消息"):
            yield f"data: {json.dumps({'type': event.type.value, 'content': event.content}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

### CLI 脚本接入

```python
import asyncio
from agent_core import Engine, OpenAILLM, LLMConfig, Rule, tool

@tool()
def search_docs(keyword: str):
    """搜索内部文档"""
    return f"找到与「{keyword}」相关的文档 3 篇"

async def main():
    llm = OpenAILLM(config=LLMConfig(base_url="...", model="..."))
    rule = Rule(name="doc助手", system_prompt="...")
    engine = Engine(llm=llm, rule=rule, tools=[search_docs()])

    async for event in engine.run("搜索部署文档"):
        if event.type.name == "RESULT":
            print(event.content)

asyncio.run(main())
```

---

## 进阶

### confirm 确认机制

工具标记 `confirm=True` 后，LLM 发起调用时 Engine 不会立即执行，而是：

1. `yield history_trace`（当前对话历史，供前端持久化）
2. `yield need_confirm(state_dict)`（引擎完整状态）
3. `return`（生成器暂停，SSE 流结束）

前端收到后展示确认卡片：

- **用户确认** → 调用 `engine.resume(state_dict)` → 执行工具 → 继续循环
- **用户取消** → 丢弃状态，前端在下一轮 `run()` 时将"已取消"上下文传入 history

关键设计：**cancel 不丢失上下文**。取消时 LLM 在下一轮能看到历史记录中的取消消息，不会重复提交同一个操作。

### terminal 终结工具

标记 `terminal=True` 的工具执行后，Engine 直接结束，不再调 LLM。适用于"提交计划"、"发送通知"这类最终操作。

terminal 工具的结果会尝试 `json.loads` 解析，成功则 `result` 事件输出 dict（方便前端获取结构化数据如 `plan_id`），否则输出原始字符串。

### @tool inject 依赖注入

当工具需要外部依赖（数据库 session、HTTP 客户端等）时，用 `inject` 参数标记，这些参数不会出现在 LLM 可调用的 JSON Schema 中：

```python
@tool(inject=["db"])
def query_project(db, project_name: str):
    """查询工程项目信息"""
    record = db.query(Project).filter(Project.name == project_name).first()
    return f"找到：{record}" if record else "未找到"

# 使用时注入 db
tool_instance = query_project(db=some_session)
# LLM 只能看到 project_name 参数
```

### 自定义 LLM Provider

当需要对接非 OpenAI 格式的 API 时，实现 `LLMProvider` 接口：

```python
from agent_core import LLMProvider, ChatResult, ToolCall

class AnthropicLLM(LLMProvider):
    async def chat(self, messages, tools=None):
        # 转换 messages 为 Anthropic 格式
        # 调用 Anthropic SDK
        # 返回 ChatResult
        ...

# 自定义 Provider 可复用 Engine、Tool、Skill、Memory 的全部逻辑
tool_instance = query_project(db=some_session)
```

---

## API 参考

### agent_core.LLMConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | str | "" | LLM API 地址 |
| `api_key` | str | "" | API 密钥 |
| `model` | str | "" | 模型名称 |
| `timeout` | int | 120 | 请求超时秒数 |
| `max_retries` | int | 0 | 失败重试次数 |
| `proxy` | str or None | None | HTTP 代理地址 |

方法：`classmethod from_dict(d: dict) -> LLMConfig`

### agent_core.LLMProvider

抽象方法：`async chat(messages, tools=None) -> ChatResult`

### agent_core.OpenAILLM

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | LLMConfig or None | None | 配置对象（优先） |
| `base_url` | str | "" | 向后兼容 |
| `api_key` | str | "" | 向后兼容 |
| `model` | str | "" | 向后兼容 |
| `timeout` | int | 120 | 向后兼容 |

### agent_core.Rule

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | 必填 | 角色名称 |
| `description` | str | "" | 一句话描述 |
| `system_prompt` | str | "" | Agent 行为规范 |

### agent_core.Tool

| 属性/方法 | 类型 | 说明 |
|----------|------|------|
| `name` | property str | 工具名称 |
| `description` | property str | 工具描述 |
| `parameters` | property dict | JSON Schema |
| `confirm` | property bool | 是否需确认 |
| `terminal` | property bool | 是否终结 |
| `execute(**kwargs)` | async method | 执行工具 |
| `to_openai_format()` | method dict | 转 OpenAI 格式 |

### agent_core.tool（装饰器）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str or None | None | 工具名 |
| `description` | str or None | None | 描述 |
| `confirm` | bool | False | 是否需确认 |
| `terminal` | bool | False | 是否终结 |
| `inject` | list[str] or None | None | 注入参数 |

返回 Tool 子类，自动注册到 `ToolRegistry`。

### agent_core.Skill

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | 必填 | 技能名称 |
| `description` | str | "" | 技能描述（展示在技能清单中） |
| `content` | str | "" | 技能完整指引文本 |

### agent_core.SkillProvider

抽象方法：
- `async list_skills() -> list[Skill]`
- `async load_skill(name: str) -> Skill | None`

### agent_core.make_load_skill_tool

工厂函数，创建内置的 `load_skill` 工具供 Agent 按需加载技能。

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider` | SkillProvider | 技能存储实现 |

### agent_core.Engine

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

### agent_core 数据类

| 类 | 字段 | 说明 |
|----|------|------|
| `EventType` | StrEnum | `THINKING` / `TOOL_CALL` / `TOOL_RESULT` / `NEED_CONFIRM` / `LLM_USAGE` / `RESULT` / `HISTORY_TRACE` / `DONE` / `ERROR` |
| `Event` | `type: EventType`, `content: Any` | 引擎事件 |
| `ChatResult` | `content: str`, `tool_calls: list[ToolCall] or None`, `usage: dict or None` | LLM 响应 |
| `ToolCall` | `id: str`, `name: str`, `arguments: dict` | 工具调用请求 |

---

## 变更记录

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

---

## License

MIT
