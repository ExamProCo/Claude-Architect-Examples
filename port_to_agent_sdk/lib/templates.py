from pathlib import Path

_root = Path(__file__).parent.parent
_prompts = _root / "prompts"
_data_dir = _root / "data"


def load_prompt(name: str) -> str:
    return (_prompts / f"{name}.md").read_text()


def render(name: str, **kwargs) -> str:
    return (_prompts / f"{name}.md").read_text().format(**kwargs)


def load_data(name: str) -> str:
    return (_data_dir / name).read_text().strip()
