---
name: Agent Team Dashboard Design Contract
version: 1.0.0
status: active
colors:
  color-background: "#f6f7f9"
  color-surface: "#ffffff"
  color-surface-subtle: "#f2f5f7"
  color-border: "#dce2e7"
  color-border-strong: "#c9d3dc"
  color-text: "#1d252c"
  color-text-muted: "#667684"
  color-action: "#1f5d8c"
  color-action-hover: "#17496e"
  color-status-processing: "#2764ad"
  color-status-completed: "#1f7a4d"
  color-status-attention: "#b43b3b"
  color-status-waiting: "#946200"
  color-status-muted: "#667684"
  color-code-background: "#111820"
  color-code-text: "#eef6f4"
typography:
  font-family-base: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
  font-family-mono: "SFMono-Regular, Consolas, monospace"
  font-size-title: "26px"
  font-size-section: "15px"
  font-size-card-title: "14px"
  font-size-body: "14px"
  font-size-meta: "12px"
  line-height-tight: "1.25"
  line-height-body: "1.45"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-5: "24px"
rounded:
  radius-control: "6px"
  radius-card: "8px"
  radius-pill: "999px"
elevation:
  elevation-panel: "0 6px 18px rgba(29, 37, 44, 0.06)"
  elevation-none: "none"
components:
  component-button-height: "38px"
  component-button-padding: "0 16px"
  component-card-border: "1px solid {colors.color-border}"
  component-input-height: "38px"
  component-status-height: "24px"
  button:
    height: "38px"
    backgroundColor: "{colors.color-action}"
    textColor: "{colors.color-surface}"
    rounded: "{rounded.radius-control}"
    padding: "0 16px"
  card:
    backgroundColor: "{colors.color-surface}"
    border: "1px solid {colors.color-border}"
    rounded: "{rounded.radius-card}"
    shadow: "{elevation.elevation-panel}"
  input:
    height: "38px"
    border: "1px solid {colors.color-border}"
    rounded: "{rounded.radius-control}"
  statusBadge:
    height: "24px"
    rounded: "{rounded.radius-pill}"
    padding: "3px 9px"
---

# Agent Team Dashboard Design Contract

## Overview

This design contract governs the local Agent Team Dashboard. The product should feel like a calm operating workspace for business and product users: clear, dense enough for repeated work, and explicit about what the AI team has understood, produced, checked, and handed back for human confirmation.

The interface is not a marketing landing page. It must not use decorative gradients, oversized hero art, or visual effects that distract from run status, deliverables, gates, and risk events.

## Colors

Use neutral surfaces for most of the layout and reserve color for action and state. The main action color is a restrained blue. Status colors are semantic and stable: processing blue, completed green, attention red, waiting amber, and planned or inactive muted gray.

Avoid one-note palettes. The page should not read as all blue, all slate, all beige, or all purple. Background bands, cards, borders, and status badges should create hierarchy without relying on heavy shadows.

## Typography

Use the base system sans stack for all product UI. Keep dashboard type compact: title text is only for the product name, section headings stay modest, and card headings stay small enough for dense scanning.

Do not scale font sizes with viewport width. Do not use negative letter spacing. Use the mono stack only for raw run details, logs, code diffs, and machine-readable records inside engineering details.

## Layout

The default layout has four business zones: request entry, task records, business progress, and deliverables. Engineering details stay folded until requested.

Use an 8px spacing rhythm. Stage cards should preserve stable dimensions across states so status badges, buttons, and dynamic text do not shift the layout. On narrow screens, collapse columns before reducing type size.

## Elevation & Depth

Use `elevation-panel` only for major surfaces such as the request entry, task list, summary band, panels, and right-side deliverables. Repeated cards use borders and subtle surface color rather than heavy shadow.

Avoid nested card effects. A panel may contain repeated cards, but repeated cards should not contain additional floating cards.

## Shapes

Controls use 6px radius. Panels and cards use 8px radius. Status badges may use pill radius. Do not exceed 8px for ordinary cards or panels.

## Components

Buttons use the action color only for the primary task submission action. Secondary actions use neutral ghost buttons. Disabled artifact buttons should remain visible but quiet.

Stage cards use the same three-line content structure: what is done, what needs attention, and the next step. Quality gate cards explain readiness in business language, not artifact filenames. Engineering detail boxes use the code color pair and remain opt-in.

## Do's and Don'ts

Do:

- Keep the first screen centered on the user's brief and the five business stages.
- Use business language by default and move run IDs, raw logs, diffs, provider, model, and executor details into advanced areas.
- Make permission and environment failures visible as "needs attention" states with a plain-language reason.
- Keep design tokens in this file aligned with Dashboard CSS variables.

Don't:

- Do not expose engineering labels such as pipeline, executor, provider, model, logs, or artifacts in the default page chrome.
- Do not add gradients, decorative blobs, illustrations, or marketing hero layouts.
- Do not use rounded cards above 8px radius.
- Do not hide risk events or failed gates behind successful-looking states.
