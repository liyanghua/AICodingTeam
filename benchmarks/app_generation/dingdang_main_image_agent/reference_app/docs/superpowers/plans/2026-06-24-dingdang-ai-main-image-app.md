# Dingdang AI Main Image App Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web application from the Dingdang PRD that runs the four-stage ecommerce main-image workflow and calls a real image generation API from a server-side proxy.

**Architecture:** A dependency-free Node server serves a browser SPA and exposes a small `/api/images/generate` proxy. Pure workflow rules live in shared modules so they can be tested without the UI or network.

**Tech Stack:** Node 25 ESM, native `node:test`, native `fetch`/`FormData`, HTML/CSS/JavaScript.

---

## Chunk 1: Local App Foundation

### Task 1: Testable Workflow Core

**Files:**
- Create: `package.json`
- Create: `tests/core.test.js`
- Create: `src/shared/dingdang-core.js`

- [ ] **Step 1: Write failing workflow tests**

Tests should cover platform diagnosis, three creative方案 generation, Stage 3 baseline/planning cards, fixed Stage 4 prompt structure, and layer iteration.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL because `src/shared/dingdang-core.js` does not exist.

- [ ] **Step 3: Implement workflow core**

Create pure functions for `diagnoseInput`, `generateCreativeSchemes`, `buildVisualBaseline`, `buildPlanningCards`, `buildImagePrompt`, and `applyLayerIteration`.

- [ ] **Step 4: Run tests to verify pass**

Run: `npm test`
Expected: PASS.

### Task 2: Testable OpenAI Image Proxy

**Files:**
- Create: `tests/openai-client.test.js`
- Create: `src/server/openai-image-client.js`

- [ ] **Step 1: Write failing API adapter tests**

Tests should cover missing API key behavior, data URL validation, OpenAI request fields, and returned base64 conversion.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL because `src/server/openai-image-client.js` does not exist.

- [ ] **Step 3: Implement API adapter**

Create a native-fetch client for `POST /v1/images/edits`, accepting product/reference image data URLs and returning a browser-ready data URL.

- [ ] **Step 4: Run tests to verify pass**

Run: `npm test`
Expected: PASS.

## Chunk 2: App Server And Browser UI

### Task 3: Local Server

**Files:**
- Create: `src/server/server.js`
- Create: `.env.example`

- [ ] **Step 1: Implement static server and JSON API route**

Serve `public/` assets, add `/api/health`, and add `/api/images/generate` with structured error JSON.

- [ ] **Step 2: Smoke test server**

Run: `node src/server/server.js`
Expected: server starts and `/api/health` returns JSON.

### Task 4: Workspace UI

**Files:**
- Create: `public/index.html`
- Create: `public/styles.css`
- Create: `public/app.js`

- [ ] **Step 1: Build UI around the PRD workflow**

Create an operational workbench with intake form, stage rail, diagnosis, creative scheme single-select, visual baseline, planning table, prompt grid, image generation queue, and layer iteration controls.

- [ ] **Step 2: Browser verification**

Open the app in the in-app browser, verify desktop/mobile layout, run the workflow without an API key, and confirm the app shows a useful key/setup error instead of crashing.

## Chunk 3: Final Verification

- [ ] Run `npm test`
- [ ] Run `node --check` on server/shared/frontend JavaScript files
- [ ] Start the local server and verify `/api/health`
- [ ] Open the browser app and exercise the workflow through Stage 4
