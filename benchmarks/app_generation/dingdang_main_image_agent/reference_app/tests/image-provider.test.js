import assert from "node:assert/strict";
import test from "node:test";

import {
  generateImageFromProvider,
  resolveImageProviderConfig,
} from "../src/server/image-provider.js";

const tinyPng =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=";

test("resolveImageProviderConfig defaults to OpenAI settings", () => {
  const config = resolveImageProviderConfig({});

  assert.equal(config.provider, "openai");
  assert.equal(config.model, "gpt-image-2");
  assert.equal(config.size, "1024x1024");
  assert.equal(config.quality, "medium");
});

test("resolveImageProviderConfig reads OpenRouter settings", () => {
  const config = resolveImageProviderConfig({
    IMAGE_PROVIDER: "openrouter",
    OPENROUTER_API_KEY: "sk-or-test",
    OPENROUTER_IMAGE_MODEL: "openai/gpt-image-1",
    OPENROUTER_IMAGE_SIZE: "1024x1024",
    OPENROUTER_IMAGE_QUALITY: "high",
  });

  assert.equal(config.provider, "openrouter");
  assert.equal(config.apiKey, "sk-or-test");
  assert.equal(config.model, "openai/gpt-image-1");
  assert.equal(config.quality, "high");
});

test("generateImageFromProvider routes OpenRouter requests", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ data: [{ b64_json: "aW1hZ2U=" }] }),
    };
  };

  const result = await generateImageFromProvider({
    env: {
      IMAGE_PROVIDER: "openrouter",
      OPENROUTER_API_KEY: "sk-or-test",
      OPENROUTER_IMAGE_MODEL: "openai/gpt-image-1",
    },
    request: {
      productImageDataUrl: tinyPng,
      prompt: "生成主图",
      options: { outputFormat: "png" },
    },
    fetchImpl,
  });

  assert.equal(calls[0].url, "https://openrouter.ai/api/v1/images");
  assert.equal(result.provider, "openrouter");
  assert.equal(result.imageDataUrl, "data:image/png;base64,aW1hZ2U=");
});

test("generateImageFromProvider passes timeout from environment", async () => {
  const fetchImpl = async (_url, options) =>
    new Promise((_resolve, reject) => {
      options.signal?.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
    });

  const result = Promise.race([
    generateImageFromProvider({
      env: {
        IMAGE_PROVIDER: "openrouter",
        OPENROUTER_API_KEY: "sk-or-test",
        IMAGE_REQUEST_TIMEOUT_MS: "10",
      },
      request: {
        productImageDataUrl: tinyPng,
        prompt: "生成主图",
      },
      fetchImpl,
    }),
    new Promise((_resolve, reject) => {
      setTimeout(() => reject(new Error("test timed out waiting for provider abort")), 80);
    }),
  ]);

  await assert.rejects(() => result, /OpenRouter 图片生成超时/);
});
