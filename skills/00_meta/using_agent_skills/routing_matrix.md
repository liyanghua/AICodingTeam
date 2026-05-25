# Routing Matrix

| Phase | Missing artifact or trigger | Primary skill | Optional companion |
| --- | --- | --- | --- |
| Define | PRD or acceptance criteria missing | spec_driven_development | context_engineering |
| Define | Context is stale, huge, or missing | context_engineering | spec_driven_development |
| Plan | Work is larger than one safe step | planning_and_task_breakdown | test_driven_development |
| Execution | Implementing a vertical slice | incremental_implementation | test_driven_development |
| Execution | Tests, review, or CLI failed | debugging_and_error_recovery | test_driven_development |
| Review | Diff is ready or apply gate is near | code_review_and_quality | debugging_and_error_recovery |

Default rule: one primary skill, zero or one companion skill.
