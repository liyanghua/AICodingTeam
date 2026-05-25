from __future__ import annotations

from typing import Any


COMMAND_WORDS = (
    "帮我找",
    "帮我查",
    "找一下",
    "搜索",
    "查询",
    "筛选",
    "看看",
    "找",
    "要",
    "素材",
    "图片",
    "图",
    "的",
)


def answer_asset_query(
    text: str, *, categories: list[str], scenes: list[str]
) -> dict[str, Any]:
    query = text.strip()
    category = _first_mentioned(query, categories)
    scene = _first_mentioned(query, scenes)
    q = _residual_query(query, category, scene)
    filters = {
        "category": category,
        "scene": scene,
        "q": q,
    }
    applied = [value for value in (category, scene, q) if value]
    return {
        "message": "已按你的描述查询素材" if applied else "请补充品类、场景或关键词",
        "filters": filters,
    }


def _first_mentioned(text: str, values: list[str]) -> str:
    for value in sorted(values, key=len, reverse=True):
        if value and value in text:
            return value
    return ""


def _residual_query(text: str, *matched_tokens: str) -> str:
    q = text
    for token in (*matched_tokens, *COMMAND_WORDS):
        if token:
            q = q.replace(token, " ")
    return " ".join(q.split())
