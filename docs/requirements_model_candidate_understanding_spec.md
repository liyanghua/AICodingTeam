# Requirements Model Candidate Understanding Spec

## Summary

This specification defines how `--requirements-model` is allowed to participate in requirement understanding. The model may produce richer candidate PRD, user stories, assumptions, open questions, red-team findings, and test scenarios. It must not directly create official PRD, acceptance criteria, slices, or Codex coding prompts.

The system principle stays unchanged:

```text
strong LLM proposes candidate understanding
deterministic gates judge promotion
run artifacts are the source of truth
```

## Goals

- Replace placeholder PM-style draft artifacts with model-generated candidate understanding.
- Preserve deterministic promotion into official artifacts.
- Make requirement clarification stronger before coding starts.
- Keep secrets, raw prompts, raw logs, full diffs, `.env`, and provider credentials out of business-facing artifacts.
- Give Dashboard enough structure to show why a task is ready for planning or blocked by requirement gaps.

## Non-Goals

- Do not let the requirements model modify code.
- Do not let the model write official `prd.md`, `acceptance_criteria.md`, `context_pack.md`, coverage matrix, slices, or TDD plan directly.
- Do not inject chat history as runtime evidence.
- Do not call the model for simple deterministic tasks unless `--planning-mode llm_assisted` is explicit.
- Do not introduce a new active Project Skill or change the 8 P0 call order.

## Runtime Placement

The requirements model runs after deterministic `brief_analysis.json` and before official artifacts:

```text
brief
-> deterministic brief_analysis.json
-> requirements-model candidate generation
-> candidate schema validation and redaction
-> deterministic requirement quality gate
-> official PRD / AC / context / coverage / TDD / slices
```

When `--planning-mode deterministic` is selected, the model is never called.

When `--planning-mode auto` is selected, the model is called only for complex tasks.

When `--planning-mode llm_assisted` is selected, the model is called for every task that reaches requirement generation.

If provider configuration is missing or the model call fails, the system writes a warning artifact and falls back to deterministic placeholder draft generation without failing the whole run.

## Inputs To The Model

Only bounded, redacted inputs may be sent:

- Redacted brief.
- `requirements/brief_analysis.json`.
- Domain id, summary, risk rules, evaluation rules, allowed paths, verification commands.
- Domain capability boundary if available.
- PM-inspired templates from existing Project Skills:
  - `pm_prd_template.md`
  - `user_story_template.md`
  - `prd_red_team_template.md`
  - `pm_test_scenarios_template.md`
- Optional historical `learning_summary.json` excerpts only when already selected by deterministic memory recall and cited by path.

Inputs must not include:

- Raw chat history.
- Raw stdout/stderr.
- Full diff.
- `.env`.
- API keys, tokens, DSNs, passwords, provider secrets.
- Unbounded repository dumps.

## Candidate Output Contract

The model must return JSON. Markdown draft files are rendered from this JSON by deterministic code.

```json
{
  "schema_version": 1,
  "status": "candidate_only",
  "summary": "",
  "clarification": {
    "business_goal": "",
    "users": [],
    "operators": [],
    "core_workflow": [],
    "inputs": [],
    "outputs": [],
    "non_goals": [],
    "compatibility_requirements": [],
    "safety_constraints": [],
    "environment_dependencies": []
  },
  "open_questions": [
    {
      "id": "Q-001",
      "question": "",
      "blocking": true,
      "why_it_matters": ""
    }
  ],
  "assumptions": [
    {
      "id": "ASM-001",
      "statement": "",
      "risk": "low|medium|high",
      "needs_validation": true
    }
  ],
  "acceptance_criteria_draft": [
    {
      "id": "AC-DRAFT-001",
      "description": "",
      "observable": true,
      "testable": true,
      "evidence": []
    }
  ],
  "user_stories": [
    {
      "id": "US-001",
      "role": "",
      "capability": "",
      "value": "",
      "conversation": [],
      "confirmation": {
        "acceptance_criteria_ids": [],
        "verification": []
      }
    }
  ],
  "prd_red_team": {
    "recommendation": "promote|revise|block",
    "load_bearing_assumptions": [],
    "scope_risks": [],
    "testability_risks": [],
    "cheapest_validation": []
  },
  "test_scenarios": [
    {
      "id": "SCN-001",
      "type": "happy_path|edge_case|error_state|regression|manual_validation",
      "related_acceptance_criteria_ids": [],
      "preconditions": [],
      "steps": [],
      "expected_result": "",
      "evidence": [],
      "verification_command": "",
      "expected_red_failure": ""
    }
  ],
  "promotion_notes": {
    "facts": [],
    "assumptions": [],
    "must_not_promote": []
  }
}
```

## Draft Artifacts

Validated candidate JSON is written to:

```text
runs/<run_id>/requirements/requirement_understanding.candidate.json
```

The system renders these markdown drafts from the JSON:

```text
runs/<run_id>/requirements/clarification.md
runs/<run_id>/requirements/prd.draft.md
runs/<run_id>/requirements/user_stories.draft.md
runs/<run_id>/requirements/prd_red_team.md
runs/<run_id>/requirements/acceptance_criteria.draft.md
runs/<run_id>/requirements/open_questions.md
runs/<run_id>/requirements/assumptions.md
runs/<run_id>/planning/test_scenarios.draft.md
```

If the model is unavailable, `requirement_understanding.candidate.json` still exists with:

```json
{
  "status": "fallback_placeholder",
  "warnings": ["requirements_model_unavailable"]
}
```

## Deterministic Validation

Candidate validation must be deterministic and schema-first:

- JSON parses and has `schema_version == 1`.
- `status` is `candidate_only`.
- All ids are stable and unique within their section.
- Every draft AC is observable and testable.
- Every user story has role, capability, value, and confirmation.
- Every test scenario maps to at least one draft or official acceptance criterion.
- Blocking open questions block promotion into coding.
- Assumptions remain assumptions and are never rendered as facts.
- Red-team `block` recommendation blocks coding until human clarification.
- Allowed paths and verification commands remain bounded by domain pack or explicit inputs.
- Safety boundaries are preserved.
- Redaction finds no secrets in candidate JSON or rendered Markdown.
- Old domain leakage is flagged as context pollution.

## Promotion Rules

The candidate never promotes itself. Deterministic code may use the candidate as an input to improve official artifacts only when:

- No blocking question exists.
- Red-team recommendation is not `block`.
- Draft AC are testable.
- User stories map to AC.
- Test scenarios map to AC.
- Capability boundary is explicit.
- No secret or unsafe automation pattern is detected.

Official artifacts remain:

```text
acceptance_criteria.md
prd.md
context_pack.md
planning/acceptance_coverage_matrix.json
planning/acceptance_coverage_matrix.md
planning/tdd_plan.json
planning/tdd_plan.md
slices/<slice_id>.yaml
planning/planning_quality_report.json
requirements/requirement_quality_report.json
```

## Requirement Quality Report Additions

`requirements/requirement_quality_report.json` should include:

```json
{
  "candidate_source": "model|fallback_placeholder|deterministic_only",
  "requirements_model": "",
  "checks": [
    {"id": "candidate_schema_valid", "status": "passed|warning|failed"},
    {"id": "candidate_redacted", "status": "passed|warning|failed"},
    {"id": "user_stories_are_structured", "status": "passed|warning|failed"},
    {"id": "prd_separates_facts_assumptions_questions", "status": "passed|warning|failed"},
    {"id": "test_scenarios_map_to_acceptance", "status": "passed|warning|failed"},
    {"id": "red_team_risks_addressed", "status": "passed|warning|failed"}
  ]
}
```

## Provider Boundary

The first implementation should reuse existing provider configuration rather than introduce a new dependency stack.

Suggested v1 provider order:

1. A dedicated `--requirements-env-file` with `REQUIREMENTS_MODEL_BASE_URL` and `REQUIREMENTS_MODEL_API_KEY`.
2. Existing AICodeMirror env config when `--env-file` is already configured; v1 can reuse `AICODEMIRROR_BASE_URL` / `AICODEMIRROR_KEY` or lowercase equivalents.
2. A small internal provider adapter that can call an OpenAI-compatible chat/completions endpoint with an array command or standard library HTTP.
3. Fallback placeholder candidate if no provider is configured.

Provider requests and responses must be recorded as sanitized summaries only:

```text
runs/<run_id>/requirements/requirements_model_request.json
runs/<run_id>/requirements/requirements_model_response.json
runs/<run_id>/requirements/requirements_model_error.json
```

These files must not contain raw secrets, raw prompt dumps, raw message arrays, or full unredacted provider payloads.

## Dashboard Behavior

The Dashboard requirement node should show:

- Candidate source: model, fallback placeholder, or deterministic only.
- Model name and reasoning effort.
- Blocking open questions.
- User stories.
- PRD red-team recommendation.
- Test scenario summary.
- Requirement quality checks.
- Links to draft and official artifacts.

The Dashboard must clearly label draft artifacts as candidate understanding, not approved requirements.

## Implementation Plan

### Task 1: Candidate Schema And Fixtures

**Inputs**

- This spec.
- Existing `growth_dev/team/complex_task.py`.
- Existing `tests/test_team_runtime.py`.

**Process**

- Add a candidate schema validator helper.
- Add valid/invalid candidate fixtures in tests.
- Add redaction checks for candidate JSON and rendered Markdown.

**Outputs**

- `requirements_model_candidate_schema` helper.
- Unit tests for valid, invalid, blocking, and secret-bearing candidates.

**Acceptance**

- Invalid schema does not crash the run.
- Secret-bearing output is redacted or rejected.
- Blocking questions produce a failed requirement gate.

### Task 2: Requirements Model Provider Adapter

**Inputs**

- `ComplexTaskConfig`.
- Existing provider/env-file conventions.

**Process**

- Add a small provider adapter for requirement understanding.
- Build a bounded prompt from redacted brief, brief analysis, domain pack, capability boundary, and PM templates.
- Capture sanitized request/response summaries.
- Fall back cleanly when provider is missing or fails.

**Outputs**

- Model candidate generation path.
- `requirements_model_request.json`.
- `requirements_model_response.json` or `requirements_model_error.json`.

**Acceptance**

- Deterministic mode never calls the model.
- `llm_assisted` calls fake provider in tests.
- Provider failure writes warning artifact and continues with fallback.

### Task 3: Candidate Markdown Rendering

**Inputs**

- Validated candidate JSON.
- Existing draft artifact names.

**Process**

- Render clarification, PRD draft, user stories, red-team, assumptions, open questions, AC draft, and test scenarios from candidate JSON.
- Keep official artifacts separate.

**Outputs**

- Existing draft artifact set with model-specific content.

**Acceptance**

- Markdown contains product-specific user stories and scenarios.
- Draft labels are visible.
- Markdown is redacted.

### Task 4: Deterministic Promotion Inputs

**Inputs**

- Candidate JSON.
- Existing `_acceptance_criteria`, `_tdd_plan`, `_task_slices`.

**Process**

- Use validated candidate AC/test scenarios as inputs to improve official AC and TDD plan.
- Preserve deterministic ids and gate rules.
- Keep fallback behavior for candidate-less runs.

**Outputs**

- More specific official `acceptance_criteria.md`.
- More specific `planning/tdd_plan.json`.
- Same coverage and slice contracts.

**Acceptance**

- Historical keyword workbench run produces AC for keyword-only, no image search, video filtering, TOP N, compatibility, UI state, and test evidence.
- Every official AC has coverage and TDD mapping.

### Task 5: Dashboard And Docs

**Inputs**

- Candidate source and quality checks.
- Draft artifacts.

**Process**

- Add candidate source summary to Dashboard state.
- Label model-generated drafts clearly.
- Update README and Project Skills docs.

**Outputs**

- Dashboard requirement node shows model candidate evidence.
- Docs explain model/gate/artifact boundary.

**Acceptance**

- Dashboard works when candidate is model-generated, fallback, or absent.
- Docs keep "rules judge, artifacts are facts" principle explicit.

## Test Plan

```bash
python3 -m unittest tests.test_team_runtime -v
python3 -m unittest tests.test_dashboard -v
python3 -m unittest tests.test_project_skills -v
python3 -m unittest discover -s tests -v
```

Required cases:

- Deterministic mode does not call requirements model.
- Auto simple task does not call model.
- Auto complex task calls fake model.
- LLM-assisted task calls fake model.
- Invalid model JSON falls back with warning.
- Blocking question blocks coding.
- Red-team block blocks coding.
- Assumption is not promoted as fact.
- Candidate AC and test scenarios improve official AC/TDD plan.
- Candidate artifacts are redacted.
- Dashboard labels candidate source and draft artifacts.
