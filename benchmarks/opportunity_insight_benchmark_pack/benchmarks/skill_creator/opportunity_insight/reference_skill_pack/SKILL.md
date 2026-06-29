---
name: ecommerce-opportunity-insight
description: Use this skill when the user needs to discover ecommerce opportunities from keyword, competitor, content, review, or sales data. Do not use it for generic reporting or unsupported direct platform operations.
---

# Ecommerce Opportunity Insight Skill

## Goal
Generate grounded ecommerce opportunity cards from business data and knowledge.

## Use when
- The user wants to identify new product opportunities.
- The user wants to analyze keyword, competitor, content, or review signals.
- The user wants evidence-backed action recommendations.

## Do not use when
- The user only asks for a simple dashboard.
- The task requires unauthorized platform operations.
- The available data is too weak and the user expects a deterministic conclusion.
- The user asks to directly modify production ecommerce systems.

## Required inputs
- Category
- Keyword data
- Competitor data

Optional inputs: content data, review data, sales data, supply-chain constraints, brand positioning, target platform.

## Process
1. Validate required data fields.
2. Normalize numeric and categorical fields.
3. Classify demand scenarios.
4. Score demand strength.
5. Score competition intensity.
6. Identify price-band gaps.
7. Build evidence packs.
8. Generate opportunity cards.
9. Generate action recommendations.
10. Review grounding, confidence and risk.

## Output rules
Each opportunity card must include opportunity title, target user, demand scenario, pain point, keyword cluster, evidence pack, opportunity score, confidence, recommended actions and risk notes.

## Safety and quality rules
- Never make strong claims without evidence.
- Reduce confidence when data coverage is weak.
- Show missing fields explicitly.
- Do not directly modify production ecommerce systems.
- Do not store secrets, tokens or private credentials.
- Do not treat high search volume as sufficient proof of opportunity.

## Failure handling
- Missing required data: ask for data or use sample data with warning.
- Low confidence: output hypothesis, not conclusion.
- Tool failure: fallback to partial report and mark blocker.
- User disagreement: create Failure Card and propose Skill patch.

## RSI feedback
Collect user acceptance, edits, downstream task creation, business outcome, failed claims, missing fields and tool failures. Update knowledge contract, data contract, scoring rubric, examples, negative cases and execution plan.
