import assert from "node:assert/strict";
import test from "node:test";

import {
  generateOpenRouterImage,
  toInputReference,
} from "../src/server/openrouter-image-client.js";

const tinyPng =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=";

test("toInputReference accepts image data URLs for OpenRouter input_references", () => {
  assert.deepEqual(toInputReference(tinyPng), {
    type: "image_url",
    image_url: { url: tinyPng },
  });
});

test("generateOpenRouterImage rejects when API key is missing", async () => {
  await assert.rejects(
    () =>
      generateOpenRouterImage({
        apiKey: "",
        productImageDataUrl: tinyPng,
        prompt: "生成主图",
      }),
    /OPENROUTER_API_KEY/,
  );
});

test("generateOpenRouterImage sends JSON image request with references", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({
        data: [{ b64_json: "b3BlbnJvdXRlci1pbWFnZQ==" }],
        usage: { cost: 0.04 },
      }),
    };
  };

  const result = await generateOpenRouterImage({
    apiKey: "sk-or-test",
    productImageDataUrl: tinyPng,
    referenceImageDataUrl: tinyPng,
    prompt: "生成主图",
    model: "openai/gpt-image-1",
    size: "1024x1024",
    quality: "high",
    outputFormat: "png",
    fetchImpl,
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://openrouter.ai/api/v1/images");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers.Authorization, "Bearer sk-or-test");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");

  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.model, "openai/gpt-image-1");
  assert.equal(body.prompt, "生成主图");
  assert.equal(body.size, "1024x1024");
  assert.equal(body.quality, "high");
  assert.equal(body.output_format, "png");
  assert.equal(body.input_references.length, 2);
  assert.equal(body.input_references[0].image_url.url, tinyPng);
  assert.equal(result.imageDataUrl, "data:image/png;base64,b3BlbnJvdXRlci1pbWFnZQ==");
  assert.deepEqual(result.usage, { cost: 0.04 });
});

test("generateOpenRouterImage surfaces OpenRouter errors", async () => {
  const fetchImpl = async () => ({
    ok: false,
    status: 429,
    json: async () => ({ error: { message: "rate limited" } }),
  });

  await assert.rejects(
    () =>
      generateOpenRouterImage({
        apiKey: "sk-or-test",
        productImageDataUrl: tinyPng,
        prompt: "生成主图",
        fetchImpl,
      }),
    /OpenRouter 图片生成失败 \(429\): rate limited/,
  );
});

test("generateOpenRouterImage aborts stalled requests with a clear timeout error", async () => {
  const fetchImpl = async (_url, options) =>
    new Promise((_resolve, reject) => {
      options.signal?.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
    });

  const result = Promise.race([
    generateOpenRouterImage({
      apiKey: "sk-or-test",
      productImageDataUrl: tinyPng,
      prompt: "生成主图",
      timeoutMs: 10,
      fetchImpl,
    }),
    new Promise((_resolve, reject) => {
      setTimeout(() => reject(new Error("test timed out waiting for client abort")), 80);
    }),
  ]);

  await assert.rejects(() => result, /OpenRouter 图片生成超时/);
});
