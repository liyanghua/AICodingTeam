# Frontend Test Patterns

Use frontend checks to protect the Dashboard as a business-facing AI team workspace.

## Required States

- Default: user sees brief input, task records, stages, quality gates, and next action.
- Loading: user sees that the AI team has started work.
- Empty: no runs or no artifact is explained in business language.
- Success: completed run shows delivery readiness and review/test evidence.
- Error: failed run shows a clear business reason and next step.

## Language Layer

- Default UI should avoid engineering-first words such as executor, provider, raw log, or model.
- Engineering details remain available in advanced settings or engineering details.
- i18n keys should be used instead of hardcoded business copy.

## Layout

- Respect `DESIGN.md` tokens.
- Avoid overlapping text on narrow widths.
- Cards should use stable dimensions and status badges.
