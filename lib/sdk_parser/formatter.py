import json


def format_message(message) -> str:
    """Format a claude_agent_sdk message object into a human-readable string."""
    type_name = type(message).__name__

    if type_name == "SystemMessage":
        return _format_system(message)
    elif type_name == "AssistantMessage":
        return _format_assistant(message)
    elif type_name == "UserMessage":
        return _format_user(message)
    elif type_name == "ResultMessage":
        return _format_result(message)
    else:
        return f"[{type_name}] {message}"


def _format_system(message) -> str:
    data = message.data if hasattr(message, "data") else {}
    session_id = data.get("session_id", "unknown")[:8]
    model = data.get("model", "unknown")
    cwd = data.get("cwd", "unknown")
    tools = data.get("tools", [])
    tool_names = [t if isinstance(t, str) else t.get("name", str(t)) for t in tools]
    return (
        f"[Session] {session_id} | Model: {model} | CWD: {cwd}\n"
        f"          Tools: {', '.join(tool_names[:8])}"
        + (" ..." if len(tool_names) > 8 else "")
    )


def _format_assistant(message) -> str:
    lines = []
    content = getattr(message, "content", [])
    for block in content:
        block_type = type(block).__name__
        if block_type == "ThinkingBlock":
            thinking = getattr(block, "thinking", "")
            preview = thinking[:200].replace("\n", " ")
            suffix = "..." if len(thinking) > 200 else ""
            lines.append(f"[Thinking] {preview}{suffix}")
        elif block_type == "TextBlock":
            text = getattr(block, "text", "")
            lines.append(f"[Claude] {text}")
        elif block_type == "ToolUseBlock":
            name = getattr(block, "name", "unknown")
            inp = getattr(block, "input", {})
            try:
                inp_str = json.dumps(inp)
            except Exception:
                inp_str = str(inp)
            lines.append(f"[Tool: {name}] Input: {inp_str}")
        else:
            lines.append(f"[{block_type}] {block}")
    return "\n".join(lines) if lines else "[AssistantMessage] (empty)"


def _format_user(message) -> str:
    lines = []
    content = getattr(message, "content", [])
    for block in content:
        block_type = type(block).__name__
        if block_type == "ToolResultBlock":
            is_error = getattr(block, "is_error", False)
            result_content = getattr(block, "content", "")
            label = "[Tool Error]" if is_error else "[Tool Result]"
            lines.append(f"{label} {result_content}")
        else:
            lines.append(f"[{block_type}] {block}")
    return "\n".join(lines) if lines else "[UserMessage] (empty)"


def _format_result(message) -> str:
    is_error = getattr(message, "is_error", False)
    result = getattr(message, "result", "")
    stop_reason = getattr(message, "stop_reason", "unknown")
    num_turns = getattr(message, "num_turns", "?")
    duration_ms = getattr(message, "duration_ms", 0)
    cost = getattr(message, "total_cost_usd", None)

    status = "ERROR" if is_error else "Done"
    cost_str = f" | ${cost:.4f}" if cost is not None else ""
    lines = [
        f"[{status}] {num_turns} turns{cost_str} | {duration_ms}ms | stop: {stop_reason}"
    ]
    if result:
        lines.append(f"[Result] {result}")
    return "\n".join(lines)
