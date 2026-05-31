# Implementation Completion Gate

## Decision

- `ready_for_review`: all gates passed.
- `needs_more_work`: one or more gates failed or need evidence.

## Gates

| Gate | Status | Evidence |
| --- | --- | --- |
| all_slices_completed | pending | Every planned slice has a completed trace. |
| all_acceptance_criteria_covered | pending | Coverage matrix shows every acceptance criterion covered by completed slices. |
| required_tests_passed | pending | Required verification commands passed. |
| no_open_blockers | pending | Slice traces and implementation trace have no open blockers. |
| no_unrelated_changes | pending | Diff only touches allowed paths and expected files. |
| final_report_mentions_coverage | pending | Final report explains how acceptance criteria were satisfied. |

## Notes

Completion means the original requirement is satisfied, not merely that each slice ran.
