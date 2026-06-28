.PHONY: install test compile lint

install:
	pip install -e .[dev]

test:
	pytest -q

compile:
	python -m doc_to_skill.cli compile --input examples/source_docs/20260519市场分析洞察元策略.md --output build/market_insight_skill

lint:
	ruff check src tests
