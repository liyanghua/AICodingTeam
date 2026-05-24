# Acceptance Criteria

## Must Pass

- Given <context>, when <user action>, then <observable result>.
- Given <failure condition>, when <system handles it>, then <user sees useful next step>.
- Given <completed run>, when <reviewer checks artifacts>, then <required artifact exists>.

## Should Pass

- Non-critical UX or workflow behavior.
- Nice-to-have evidence or report detail.

## Must Not Happen

- Secret, provider key, or `.env` value appears in artifacts.
- AI coding edits outside allowed paths.
- Dashboard exposes engineering details by default to business users.

## Verification

- Unit:
- Integration:
- Manual:
