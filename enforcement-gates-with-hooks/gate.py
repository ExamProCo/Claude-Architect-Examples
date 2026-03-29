"""
gate.py  —  Event-driven enforcement gates for multi-step LLM coordinators.

Architecture
------------
Hooks are registered as listeners on named events. When the coordinator calls
``gate.execute(...)``, the gate fires events in order:

    pre_tool   →  [all pre listeners run; any can block]
    ↓ (if not blocked)
    tool runs
    ↓
    post_tool  →  [all post listeners run; warnings only]

The coordinator loop only calls ``gate.execute()`` — it never manually checks
pre/post state. The gate handles interception transparently.

Usage
-----
    gate = EnforcementGate()

    # Register listeners on events
    gate.on("pre_tool",  max_calls_listener("screening_agent", max_n=6))
    gate.on("pre_tool",  no_duplicate_listener("screening_agent", arg_key="question"))
    gate.on("post_tool", log_listener())

    # In your tool-use loop — one call, hooks fire automatically:
    result = await gate.execute(
        tool_name  = block.name,
        tool_input = block.input,
        executor   = lambda: call_screening_agent(client, question, job, resume),
    )

    if result.blocked:
        tool_results.append({
            "type": "tool_result", "tool_use_id": block.id,
            "content": f"[GATE BLOCKED] {result.reason}", "is_error": True,
        })
    else:
        tool_results.append({
            "type": "tool_result", "tool_use_id": block.id,
            "content": result.value,
        })
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

@dataclass
class GateState:
    call_sequence:    list[str]              = field(default_factory=list)
    call_counts:      dict[str, int]         = field(default_factory=dict)
    per_tool_history: dict[str, list[dict]]  = field(default_factory=dict)
    violations:       list[dict]             = field(default_factory=list)


@dataclass
class ExecutionResult:
    blocked: bool
    reason:  str   = ""        # set when blocked=True
    value:   str   = ""        # set when blocked=False


# Listener signatures
#   pre_tool  listener: (tool_name, tool_input, state) -> (blocked: bool, reason: str)
#   post_tool listener: (tool_name, tool_input, result, state) -> None
PreListener  = Callable[[str, dict, GateState], tuple[bool, str]]
PostListener = Callable[[str, dict, str, GateState], None]


# ---------------------------------------------------------------------------
# EnforcementGate
# ---------------------------------------------------------------------------

class EnforcementGate:
    """
    Event-driven gate. Register listeners with ``on()``, then call
    ``execute()`` — the gate fires events and handles interception internally.
    """

    EVENTS = ("pre_tool", "post_tool")

    def __init__(self) -> None:
        self._listeners: dict[str, list[Any]] = {e: [] for e in self.EVENTS}
        self.state = GateState()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def on(self, event: str, listener: Callable) -> "EnforcementGate":
        """Register a listener on a named event. Returns self for chaining."""
        if event not in self.EVENTS:
            raise ValueError(f"Unknown event '{event}'. Valid: {self.EVENTS}")
        self._listeners[event].append(listener)
        return self

    # ------------------------------------------------------------------
    # Execution entry point — the only method the loop needs to call
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_name:  str,
        tool_input: dict,
        executor:   Callable[[], str | Awaitable[str]],
    ) -> ExecutionResult:
        """
        Fire pre_tool listeners → run executor (if not blocked) → fire post_tool listeners.

        Parameters
        ----------
        tool_name:  name of the tool being called
        tool_input: the tool's input dict
        executor:   zero-arg callable (sync or async) that actually runs the tool
        """
        # ── fire pre_tool ────────────────────────────────────────────────
        for listener in self._listeners["pre_tool"]:
            blocked, reason = listener(tool_name, tool_input, self.state)
            if blocked:
                self.state.violations.append({
                    "stage": "pre_tool",
                    "tool":  tool_name,
                    "input": tool_input,
                    "reason": reason,
                    "after_n_calls": sum(self.state.call_counts.values()),
                })
                return ExecutionResult(blocked=True, reason=reason)

        # ── record + run tool ────────────────────────────────────────────
        self.state.call_sequence.append(tool_name)
        self.state.call_counts[tool_name] = self.state.call_counts.get(tool_name, 0) + 1
        self.state.per_tool_history.setdefault(tool_name, []).append(tool_input)

        raw = executor()
        result = await raw if asyncio.iscoroutine(raw) else raw

        # ── fire post_tool ───────────────────────────────────────────────
        for listener in self._listeners["post_tool"]:
            listener(tool_name, tool_input, result, self.state)

        return ExecutionResult(blocked=False, value=result)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset state for a new coordinator run."""
        self.state = GateState()

    # ------------------------------------------------------------------
    # Audit helper
    # ------------------------------------------------------------------

    def summary(self) -> str:
        lines = [
            f"  Total calls  : {sum(self.state.call_counts.values())}",
            f"  Per-tool     : {dict(self.state.call_counts)}",
            f"  Violations   : {len(self.state.violations)}",
        ]
        for v in self.state.violations:
            lines.append(
                f"    [{v['stage'].upper()}] after {v['after_n_calls']} calls — {v['reason']}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-in pre_tool listeners
# ---------------------------------------------------------------------------

def max_calls_listener(tool_name: str, max_n: int) -> PreListener:
    """Block once tool_name has been called max_n times."""
    def listener(name: str, inp: dict, state: GateState) -> tuple[bool, str]:
        if name != tool_name:
            return False, ""
        count = state.call_counts.get(tool_name, 0)
        if count >= max_n:
            return True, (
                f"'{tool_name}' has already been called {count} time(s); "
                f"limit is {max_n}. Synthesize a final answer from existing results."
            )
        return False, ""
    return listener


def no_duplicate_listener(tool_name: str, arg_key: str) -> PreListener:
    """Block a call whose arg_key value exactly matches a previous call."""
    def listener(name: str, inp: dict, state: GateState) -> tuple[bool, str]:
        if name != tool_name:
            return False, ""
        value = str(inp.get(arg_key, "")).strip().lower()
        for prev in state.per_tool_history.get(tool_name, []):
            if str(prev.get(arg_key, "")).strip().lower() == value:
                return True, (
                    f"Duplicate blocked: already called '{tool_name}' with "
                    f"{arg_key}='{inp.get(arg_key)}'. Ask a different question."
                )
        return False, ""
    return listener


def required_before_listener(tool_name: str, must_precede: str) -> PreListener:
    """Block tool_name until must_precede has appeared in the call sequence."""
    def listener(name: str, inp: dict, state: GateState) -> tuple[bool, str]:
        if name != tool_name:
            return False, ""
        if must_precede not in state.call_sequence:
            return True, (
                f"'{tool_name}' cannot run yet — '{must_precede}' must be called first."
            )
        return False, ""
    return listener


def required_dimensions_listener(
    tool_name:        str,
    required_keywords: list[str],
    arg_key:          str = "question",
    enforce_after_n:  int = 3,
) -> PreListener:
    """
    After enforce_after_n calls, block further calls until every keyword in
    required_keywords appears (substring, case-insensitive) in the call history.
    """
    def listener(name: str, inp: dict, state: GateState) -> tuple[bool, str]:
        if name != tool_name:
            return False, ""
        if state.call_counts.get(tool_name, 0) < enforce_after_n:
            return False, ""
        history  = state.per_tool_history.get(tool_name, [])
        combined = " ".join(str(h.get(arg_key, "")) for h in history).lower()
        missing  = [kw for kw in required_keywords if kw.lower() not in combined]
        if missing:
            return True, (
                f"Required dimensions not yet covered: {missing}. "
                f"Address these before making additional calls."
            )
        return False, ""
    return listener


# ---------------------------------------------------------------------------
# Built-in post_tool listeners
# ---------------------------------------------------------------------------

def log_listener(label: str = "") -> PostListener:
    """Print every completed tool call (debugging)."""
    def listener(name: str, inp: dict, result: str, state: GateState) -> None:
        prefix = f"[{label}] " if label else ""
        total  = sum(state.call_counts.values())
        print(f"  {prefix}[post #{total}] {name} -> {result[:80]}...")
    return listener
