# PM Test Scenarios Template

Use this template to translate product acceptance criteria into executable and manual validation scenarios before implementation.

## Scenario Format

`SCN-001`

- Type: happy path | edge case | error state | regression | manual validation
- User/operator:
- Related acceptance criteria:
- Preconditions:
- Steps:
  1. 
- Expected result:
- Evidence:
- Verification command:
- Expected red failure:

## Required Scenario Coverage

- Happy path for the main workflow.
- Edge case for missing, partial, duplicate, or boundary inputs.
- Error state for permission, unavailable dependency, invalid config, or unsafe action.
- Regression scenario for existing behavior that must remain compatible.
- Manual validation scenario when real device, external service, deployment, or production evidence is required.

## Quality Notes

- Prefer public behavior over private implementation details.
- Each new behavior must have at least one scenario.
- Each scenario must map to at least one acceptance criterion.
- Red failure must explain what is missing before implementation.
