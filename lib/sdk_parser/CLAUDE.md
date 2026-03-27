# sdk_parser

Formats raw `claude_agent_sdk` message objects into human-readable terminal output.

## What it does

Converts noisy output like:

```
AssistantMessage(content=[ThinkingBlock(thinking='Let me find...', signature='...'), ToolUseBlock(id='toolu_...', name='Glob', input={'pattern': '**/*.rb'})])
```

Into readable output like:

```
[Thinking] Let me find the hello_world.rb file first.
[Tool: Glob] Input: {"pattern": "**/*.rb"}
[Tool Result] No files found
[Claude] I couldn't find a file named `hello_world.rb`...
[Done] 2 turns | $0.036 | 4864ms | stop: end_turn
```

## Importing in projects within this repo

### Option 1: sys.path insert (works from any subdirectory)

Add this at the top of your script, adjusting the relative path to reach the repo root:

```python
import sys, os
# From a project one level deep (e.g., hello_world/main.py):
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
# From a project two levels deep (e.g., examples/foo/main.py):
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))

from sdk_parser import format_message
```

### Option 2: PYTHONPATH env var (run from repo root)

```bash
PYTHONPATH=lib python hello_world/main.py
```

Or set it in your shell session:

```bash
export PYTHONPATH=/path/to/Claude-Architect-Examples/lib
python hello_world/main.py
```

## Usage

```python
from sdk_parser import format_message

async for message in query(prompt="...", options=...):
    print(format_message(message))
```

## Output format per message type

| Message type     | Output                                                          |
|------------------|-----------------------------------------------------------------|
| `SystemMessage`  | Session ID, model, CWD, available tools                        |
| `AssistantMessage` → `ThinkingBlock` | `[Thinking] <first 200 chars of reasoning>` |
| `AssistantMessage` → `TextBlock`     | `[Claude] <response text>`                  |
| `AssistantMessage` → `ToolUseBlock`  | `[Tool: <name>] Input: <json>`              |
| `UserMessage` → `ToolResultBlock`    | `[Tool Result] <content>` or `[Tool Error]` |
| `ResultMessage`  | `[Done] <turns> | $<cost> | <ms>ms | stop: <reason>`           |
