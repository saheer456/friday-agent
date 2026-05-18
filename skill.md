# FRIDAY ARCHITECTURE REFACTOR SKILL

## OBJECTIVE

Transform FRIDAY from a feature-based assistant into a scalable modular AI agent platform.

The implementation must introduce:

* Tool Registry System
* Provider Abstraction Layer
* Streaming Event Bus
* Async Task Queue
* Permission Sandbox
* Tool Result Memory
* Multi-Step Planning Engine

The architecture must remain lightweight, async-first, modular, and compatible with local/self-hosted deployment.

---

# CORE ARCHITECTURE RULES

## 1. NEVER hardcode tools inside brain.py

brain.py must only orchestrate:

* planning
* routing
* memory injection
* response generation

Tool execution logic must be externalized.

---

## 2. ALL tools follow ONE interface

Create:

backend/tools/base.py

```python
from abc import ABC, abstractmethod

class BaseTool(ABC):
    name: str
    description: str
    permissions: list[str] = []

    @abstractmethod
    async def run(self, args: dict):
        pass
```

---

# TOOL REGISTRY SYSTEM

Create:

backend/tools/registry.py

Requirements:

* auto-register tools
* dynamic imports
* lazy loading
* enable/disable tools
* permission-aware execution

Structure:

```python
TOOLS = {}

def register(tool):
    TOOLS[tool.name] = tool

def get_tool(name):
    return TOOLS.get(name)
```

Every tool folder:

```text
tools/
  weather/
    tool.py
  browser/
    tool.py
```

Each tool self-registers on import.

---

# PROVIDER ABSTRACTION LAYER

Create:

backend/providers/

Supported providers:

* Groq
* Cerebras
* OpenAI
* OpenRouter
* local Ollama

All providers MUST expose the same API.

Base interface:

```python
class BaseProvider:
    async def chat(self, messages, **kwargs):
        pass

    async def stream(self, messages, **kwargs):
        pass
```

brain.py must NEVER directly call Groq/OpenAI SDKs.

Use:

```python
provider_manager.generate(...)
```

Add:

* fallback providers
* timeout handling
* retries
* rate-limit handling
* provider health tracking

---

# STREAMING EVENT BUS

Create:

backend/events/

Purpose:

* decouple frontend updates from execution logic

Use async pub/sub.

Events:

* thinking_started
* tool_called
* tool_finished
* response_chunk
* error
* memory_saved
* plan_created

Frontend subscribes via SSE/websocket.

No direct print/log streaming from brain.py.

---

# ASYNC TASK QUEUE

Create:

backend/tasks/

Purpose:

* long-running background execution

Examples:

* file ingestion
* youtube processing
* embeddings
* web crawling
* memory indexing

Requirements:

* asyncio.Queue based
* task IDs
* progress tracking
* cancellation support

Do NOT block chat loop.

---

# PERMISSION SANDBOX

Create:

backend/security/

Each tool must declare permissions:

Examples:

* filesystem.read
* filesystem.write
* browser.open
* shell.execute
* network.external

Before execution:

```python
permission_manager.validate(tool)
```

Add:

* allowlist
* denylist
* safe mode
* confirmation-required actions

Dangerous tools MUST require explicit approval.

---

# TOOL RESULT MEMORY

Create:

backend/memory/tool_memory.py

Store:

* tool inputs
* outputs
* timestamps
* success/failure
* execution duration

Purpose:

* debugging
* planning context
* agent self-reflection
* optimization

Example:

* avoid repeating failed actions
* remember previous searches

---

# MULTI-STEP PLANNING ENGINE

Create:

backend/planner/

Planner responsibilities:

* decompose goals
* select tools
* track execution state
* retry failures
* summarize outcomes

Architecture:

```python
Goal
 ├── Step 1
 ├── Step 2
 └── Step 3
```

Each step contains:

* reasoning
* selected tool
* status
* result

Use lightweight planning first.
DO NOT build autonomous recursive agents yet.

Avoid infinite loops.

---

# MEMORY INTEGRATION

Planner and tools must both integrate with:

* short-term memory
* long-term memory
* semantic memory

Tool outputs can become memories if importance threshold is met.

---

# LOGGING

Create structured logs:

```json
{
  "event": "tool_execution",
  "tool": "weather",
  "duration_ms": 221,
  "success": true
}
```

No random print() debugging.

---

# FUTURE EXPANSION TARGETS

Architecture must support future:

* multi-agent systems
* local model routing
* MCP servers
* voice pipelines
* autonomous workflows
* cloud deployment
* mobile clients
* plugin marketplace

---

# IMPORTANT DESIGN PRINCIPLES

* async-first
* modular
* composable
* provider-agnostic
* event-driven
* memory-aware
* lightweight
* locally runnable

Avoid:

* giant god classes
* duplicated provider logic
* direct SDK coupling
* hidden global state
* synchronous blocking workflows

---

# FINAL GOAL

FRIDAY should evolve into:

"A modular local-first cognitive operating system."

Not:
"another ChatGPT clone with extra buttons."
