from doc_to_skill.schemas import DataRequirement, ToolContract
from doc_to_skill.tool_registry import ToolRegistry
from doc_to_skill.tool_resolver import ToolResolver


def test_tool_resolver_matches_internal_tool():
    registry = ToolRegistry()
    registry.register(ToolContract(tool_id="internal_api.category_top_products", name="x", type="internal_data_tool", domain="market_insight"))
    req = DataRequirement(id="r1", description="x", preferred_sources=["internal_dw.category_top_products"])
    result = ToolResolver(registry).resolve(req)
    assert result["status"] == "matched"
    assert result["selected_tool"] == "internal_api.category_top_products"
