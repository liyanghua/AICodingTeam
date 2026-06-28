from __future__ import annotations

from .schemas import DataRequirement
from .tool_registry import ToolRegistry


class ToolResolver:
    """Resolve a data requirement to the best available tool."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def resolve(self, requirement: DataRequirement) -> dict:
        candidates = requirement.preferred_sources + requirement.fallback_sources
        converted = [self._source_to_tool_id(c) for c in candidates]
        for tool_id in converted:
            if self.registry.get(tool_id):
                return {
                    "data_requirement": requirement.id,
                    "selected_tool": tool_id,
                    "fallback_tools": [x for x in converted if x != tool_id],
                    "status": "matched",
                }
        return {
            "data_requirement": requirement.id,
            "selected_tool": None,
            "fallback_tools": converted,
            "status": "missing_tool",
        }

    def _source_to_tool_id(self, source: str) -> str:
        replacements = {
            "internal_dw.": "internal_api.",
            "bi_api.": "bi_api.",
            "browser.": "browser.",
            "external_web.": "external_web.",
            "compute.": "compute.",
            "manual_upload.": "manual_upload.",
        }
        for prefix, repl in replacements.items():
            if source.startswith(prefix):
                return source.replace(prefix, repl, 1)
        return source
