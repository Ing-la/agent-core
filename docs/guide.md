# 使用指南

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
        return f"处理了 {param1}"
```

### @tool 装饰器

装饰器方式自动处理样板代码，从类型标注推断 JSON Schema。

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

Rule 和 Skill 是正交关系：Rule 决定了"你是谁"，Skill 提供了"你该领域的专业知识"。

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

Agent 初始状态只注入技能列表（name + description），完整内容通过 `load_skill` 工具按需加载。

### SkillProvider

技能存储抽象接口。业务层实现 `list_skills()` 和 `load_skill()` 两个方法。

```python
from agent_core import SkillProvider, Skill

class JsonSkillProvider(SkillProvider):
    async def list_skills(self) -> list[Skill]: ...
    async def load_skill(self, name: str) -> Skill | None: ...
```

内置 `make_load_skill_tool(provider)` 工厂函数，创建 `load_skill` 工具供 Agent 运行时按需加载。

```python
from agent_core import make_load_skill_tool

provider = JsonSkillProvider("skills/")
skill_tool = make_load_skill_tool(provider)
engine = Engine(llm=llm, rule=rule, tools=[*other_tools, skill_tool], skill_provider=provider)
```

### LLMConfig

```python
from agent_core import LLMConfig

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

```python
from agent_core import LLMProvider, OpenAILLM

# 内置 OpenAI 兼容实现
llm = OpenAILLM(config=LLMConfig(base_url="...", api_key="...", model="..."))

# 自定义 Provider（对接 Anthropic / Google 等）
class AnthropicLLM(LLMProvider):
    async def chat(self, messages, tools=None):
        ...
```

### contrib — 开箱即用的默认实现

```python
from agent_core.contrib import JSONFileMemoryProvider, JSONFileSkillProvider

memory = JSONFileMemoryProvider("memory.json")
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

#### ReAct 循环流程

```
run(user_message):
  1. 构建 messages:
     - extra_context
     - rule.system_prompt
     - 可用技能列表（name + description）
     - memory context（如果启用 MemoryEngine）
     - history
     - user_message
  2. tool_defs = [t.to_openai_format() for t in tools]
  3. _react_loop:
     - LLM.chat(messages, tool_defs)
     - 有 tool_call → 执行 → 继续
     - 无 tool_call → yield result + done
  4. Agent 可调用 load_skill("XXX") 注入领域知识
```

### Event

Engine 以 `AsyncGenerator[Event]` 对外输出。

```python
@dataclass
class Event:
    type: EventType
    content: Any
```

事件类型见 [SSE 事件协议](#sse-事件协议)。

### MemoryProvider

| 方法 | 说明 |
|------|------|
| `save(user_id, key, data)` | 保存一条记忆 |
| `load(user_id, key)` | 读取一条记忆 |
| `delete(user_id, key)` | 删除一条记忆 |
| `list_keys(user_id, prefix)` | 列出某用户所有匹配前缀的 key |

### MemoryEngine

三层记忆：

| 层次 | key 前缀 | 写入者 | 读取者 |
|------|---------|--------|--------|
| 短期记忆 | `msg:{conv_id}:{turn}:{role}` | `_store_turn()`（每轮） | 压缩/提取时读取 |
| 压缩记忆 | `summary:{conv_id}` | `_compress()`（token > 70% 触发） | 每次 `before_react()` |
| 长期记忆 | `fact:{key}` | `_extract()`（与压缩同触发） | 每次 `before_react()` |

```python
from agent_core.memory import MemoryProvider, MemoryEngine

provider = SqliteMemory()
memory_engine = MemoryEngine(provider=provider, llm=llm)
engine = Engine(llm=llm, rule=rule, tools=tools, memory_engine=memory_engine)
```

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

## 进阶

### confirm 确认机制

工具标记 `confirm=True` 后，LLM 发起调用时 Engine 不会立即执行，而是暂停等待前端确认。

- **用户确认** → `engine.resume(state_dict)` → 执行工具 → 继续循环
- **用户取消** → 丢弃状态，下一轮 `run()` 传入 history 即可

### terminal 终结工具

`terminal=True` 的工具执行后 Engine 直接结束，不再调 LLM。结果尝试 `json.loads` 解析。

### @tool inject 依赖注入

```python
@tool(inject=["db"])
def query_project(db, project_name: str):
    record = db.query(Project).filter(Project.name == project_name).first()
    return f"找到：{record}" if record else "未找到"

tool_instance = query_project(db=some_session)  # 注入 db
await tool_instance.execute(project_name="某工程")  # LLM 只传业务参数
```

### 自定义 LLM Provider

```python
class AnthropicLLM(LLMProvider):
    async def chat(self, messages, tools=None):
        # 转换 messages 为 Anthropic 格式
        # 调用 Anthropic SDK
        # 返回 ChatResult
        ...
```

---

## 集成示例

### FastAPI SSE

```python
from fastapi.responses import StreamingResponse
import json

@router.post("/chat/stream")
async def chat_stream():
    engine = Engine(llm=llm, rule=rule, tools=[...])

    async def generate():
        async for event in engine.run("用户消息"):
            yield f"data: {json.dumps({'type': event.type.value, 'content': event.content}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

### CLI

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
