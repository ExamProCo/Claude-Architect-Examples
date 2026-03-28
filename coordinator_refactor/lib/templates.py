import json
from pathlib import Path

_root = Path(__file__).parent.parent
_prompts = _root / "prompts"
_tools_dir = _root / "tools"
_data_dir = _root / "data"


def load_prompt(name: str) -> str:
    return (_prompts / f"{name}.md").read_text()


def render(name: str, **kwargs) -> str:
    return (_prompts / f"{name}.md").read_text().format(**kwargs)


def load_tools() -> list[dict]:
    return json.loads((_tools_dir / "tools.json").read_text())


def load_data(name: str) -> str:
    return (_data_dir / name).read_text().strip()
