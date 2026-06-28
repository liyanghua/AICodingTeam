import assert from "node:assert/strict";
import test from "node:test";

import {
  createRequestId,
  createServerLogger,
  sanitizeForLog,
} from "../src/server/server-logger.js";

test("createRequestId produces short traceable ids", () => {
  const id = createRequestId();

  assert.match(id, /^img_[a-z0-9]{8}$/);
});

test("sanitizeForLog removes secrets and full prompt-like values", () => {
  const sanitized = sanitizeForLog({
    apiKey: "sk-or-v1-secret",
    prompt: "这是一段很长的完整提示词，不能进入后台日志",
    nested: { OPENROUTER_API_KEY: "sk-or-v1-secret" },
    model: "openai/gpt-image-1",
  });

  assert.equal(sanitized.apiKey, "[redacted]");
  assert.equal(sanitized.prompt, "[omitted]");
  assert.equal(sanitized.nested.OPENROUTER_API_KEY, "[redacted]");
  assert.equal(sanitized.model, "openai/gpt-image-1");
});

test("createServerLogger writes structured JSON lines", () => {
  const rows = [];
  const logger = createServerLogger({
    sink: (line) => rows.push(JSON.parse(line)),
    now: () => "2026-06-24T00:00:00.000Z",
  });

  logger.info("image.generate.start", {
    requestId: "img_12345678",
    provider: "openrouter",
    hasProductImage: true,
    prompt: "不要记录完整 prompt",
  });

  assert.equal(rows.length, 1);
  assert.equal(rows[0].level, "info");
  assert.equal(rows[0].event, "image.generate.start");
  assert.equal(rows[0].requestId, "img_12345678");
  assert.equal(rows[0].provider, "openrouter");
  assert.equal(rows[0].prompt, "[omitted]");
});
