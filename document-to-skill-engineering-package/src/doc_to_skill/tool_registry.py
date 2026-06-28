from __future__ import annotations

from pathlib import Path
import yaml
from .schemas import ToolContract


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolContract] = {}

    def register(self, tool: ToolContract) -> None:
        self._tools[tool.tool_id] = tool

    def get(self, tool_id: str) -> ToolContract | None:
        return self._tools.get(tool_id)

    def load_yaml(self, path: str | Path) -> None:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        for item in data.get("tools", []):
            self.register(ToolContract(**item))

    def list_tools(self) -> list[ToolContract]:
        return list(self._tools.values())
