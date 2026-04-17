import sqlite3
from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "todos.db"

mcp = FastMCP("todo-server")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


# ── RESOURCE ──────────────────────────────────────────────────────────────────
# Resources are passive, read-only — the agent reads state without side effects.

@mcp.resource("todos://list")
def list_todos() -> str:
    """Read all todos from the database (passive, no side effects)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, done, created_at FROM todos ORDER BY id"
        ).fetchall()
    if not rows:
        return "No todos yet."
    lines = []
    for row in rows:
        status = "✓" if row["done"] else "○"
        lines.append(f"[{status}] #{row['id']}: {row['title']}  (created: {row['created_at']})")
    return "\n".join(lines)


# ── TOOLS ─────────────────────────────────────────────────────────────────────
# Tools mutate state — the agent calls them to create, update, or delete.

@mcp.tool()
def create_todo(title: str) -> str:
    """Create a new todo item."""
    with get_db() as conn:
        cursor = conn.execute("INSERT INTO todos (title) VALUES (?)", (title,))
        conn.commit()
    return f"Created todo #{cursor.lastrowid}: {title}"


@mcp.tool()
def update_todo(id: int, title: Optional[str] = None, done: Optional[bool] = None) -> str:
    """Update a todo's title and/or completion status."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (id,)).fetchone()
        if not row:
            return f"Todo #{id} not found."
        new_title = title if title is not None else row["title"]
        new_done = (1 if done else 0) if done is not None else row["done"]
        conn.execute(
            "UPDATE todos SET title = ?, done = ? WHERE id = ?",
            (new_title, new_done, id),
        )
        conn.commit()
    return f"Updated todo #{id}: title='{new_title}' done={bool(new_done)}"


@mcp.tool()
def delete_todo(id: int) -> str:
    """Delete a todo item by ID."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM todos WHERE id = ?", (id,))
        conn.commit()
    if cursor.rowcount == 0:
        return f"Todo #{id} not found."
    return f"Deleted todo #{id}"


if __name__ == "__main__":
    init_db()
    mcp.run()
