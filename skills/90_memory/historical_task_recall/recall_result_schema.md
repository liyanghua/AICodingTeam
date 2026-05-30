# Recall Result Schema

```json
{
  "schema_version": 1,
  "query": "",
  "run_id": "",
  "domain_id": "",
  "generated_at": "",
  "matches": [],
  "recommended_skills": [],
  "context_strategy": {
    "reuse": [],
    "avoid": [],
    "checklist": []
  }
}
```

Rules:

- `matches[].run_id` must cite a local historical run.
- `recommended_skills[].id` must be an active skill id from `skills/registry.yaml`.
- `context_strategy.avoid` must exclude raw logs, full diff, prompts, `.env`, and secrets.
