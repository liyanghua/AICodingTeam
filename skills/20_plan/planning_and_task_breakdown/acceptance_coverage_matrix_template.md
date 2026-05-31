# Acceptance Coverage Matrix

## Goal

Map every acceptance criterion to one or more implementation slices before coding begins.

## Matrix

| Acceptance ID | Acceptance Criterion | Covering Slices | Verification | Status |
| --- | --- | --- | --- | --- |
| AC-001 | User-visible behavior to prove. | slice-001 | `python3 -m unittest ...` | planned |

## Orphan Checks

- Orphan slice check: every slice must list at least one acceptance criterion id.
- Orphan acceptance criterion check: every acceptance criterion must list at least one covering slice.
- Unverifiable slice check: every slice must have a verification command or explicit manual evidence.

## Planning Decision

- `ready_for_implementation`: all acceptance criteria have slices and every slice is verifiable.
- `needs_revision`: any orphan slice, orphan acceptance criterion, or unverifiable slice remains.
