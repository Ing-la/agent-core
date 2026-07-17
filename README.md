<p align="center">
  <h1 align="center">agent-core</h1>
  <p align="center">轻量级 AI Agent 内核引擎<br>零非必要依赖，可嵌入任何 Python 项目</p>
</p>

---

## Features

- **ReAct 循环** — 思考 → 行动 → 观察，最经典的 Agent 范式
- **工具调用** — 继承 `Tool` 基类或 `@tool` 装饰器，两种方式定义工具
- **按需技能** — `load_skill` 工具让 Agent 运行时加载领域知识，不污染 prompt
- **三层记忆** — 短期消息 / 压缩摘要 / 长期事实，跨对话持久化
- **用户确认** — 关键操作前暂停，前端确认后恢复
- **并行执行** — 独立工具通过 `asyncio.gather` 并发
- **LLM 无关** — 内置 OpenAI 兼容实现，实现 1 个接口即可对接任何 LLM
- **MCP 支持** — 一行代码接入社区工具生态，MCP 外部工具自动转本地 Tool（可选 `pip install mcp`）
- **可嵌入** — 零非必要依赖（仅 `httpx`），复制或 pip 皆可

## Quick Start

```python
from agent_core import OpenAILLM, LLMConfig, Rule, Engine, tool

@tool()
def query_time() -> str:
    """查询当前时间"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

llm = OpenAILLM(config=LLMConfig(base_url="...", model="..."))
rule = Rule(name="助手", system_prompt="你是一个有用的助手。")
engine = Engine(llm=llm, rule=rule, tools=[query_time()])

async for event in engine.run("现在几点了？"):
    print(event.type, event.content)
```

## Install

```bash
pip install git+https://github.com/Ing-la/agent-core.git
# 或直接复制 agent_core/ 目录到项目中
```

## Documentation

| 文档 | 内容 |
|------|------|
| [使用指南](docs/guide.md) | 核心概念、快速开始、进阶用法（confirm / terminal / inject）、集成示例 |
| [架构设计](docs/architecture.md) | 文件职责、数据流、设计哲学 |
| [API 参考](docs/api.md) | 全部类、方法、参数的详细说明 |
| [变更记录](docs/changelog.md) | 版本历史 |

## License

MIT
