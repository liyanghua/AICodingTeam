import assert from "node:assert/strict";
import test from "node:test";

import {
  generateImageEdit,
  parseImageDataUrl,
} from "../src/server/openai-image-client.js";

const tinyPng =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=";

test("parseImageDataUrl validates and decodes image data URLs", () => {
  const parsed = parseImageDataUrl(tinyPng, "product");

  assert.equal(parsed.mime, "image/png");
  assert.equal(parsed.extension, "png");
  assert.ok(parsed.fileName.startsWith("product."));
  assert.ok(parsed.blob.size > 0);
});

test("generateImageEdit rejects when API key is missing", async () => {
  await assert.rejects(
    () =>
      generateImageEdit({
        apiKey: "",
        productImageDataUrl: tinyPng,
        prompt: "生成主图",
      }),
    /OPENAI_API_KEY/,
  );
});

test("generateImageEdit rejects invalid image data URLs", async () => {
  await assert.rejects(
    () =>
      generateImageEdit({
        apiKey: "sk-test",
        productImageDataUrl: "not-a-data-url",
        prompt: "生成主图",
      }),
    /产品图必须是 data:image/,
  );
});

test("generateImageEdit sends expected multipart fields and returns a browser data URL", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({
        data: [{ b64_json: "ZmFrZS1pbWFnZQ==", revised_prompt: "revised" }],
      }),
    };
  };

  const result = await generateImageEdit({
    apiKey: "sk-test",
    productImageDataUrl: tinyPng,
    referenceImageDataUrl: tinyPng,
    prompt: "生成主图",
    model: "gpt-image-2",
    size: "1024x1024",
    quality: "medium",
    outputFormat: "png",
    fetchImpl,
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.openai.com/v1/images/edits");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers.Authorization, "Bearer sk-test");
  assert.equal(calls[0].options.body.get("model"), "gpt-image-2");
  assert.equal(calls[0].options.body.get("prompt"), "生成主图");
  assert.equal(calls[0].options.body.get("size"), "1024x1024");
  assert.equal(calls[0].options.body.get("quality"), "medium");
  assert.equal(calls[0].options.body.get("output_format"), "png");
  assert.equal(calls[0].options.body.getAll("image").length, 2);
  assert.equal(result.imageDataUrl, "data:image/png;base64,ZmFrZS1pbWFnZQ==");
  assert.equal(result.revisedPrompt, "revised");
});

test("generateImageEdit surfaces OpenAI error messages", async () => {
  const fetchImpl = async () => ({
    ok: false,
    status: 400,
    json: async () => ({ error: { message: "bad request" } }),
  });

  await assert.rejects(
    () =>
      generateImageEdit({
        apiKey: "sk-test",
        productImageDataUrl: tinyPng,
        prompt: "生成主图",
        fetchImpl,
      }),
    /OpenAI 图片生成失败 \(400\): bad request/,
  );
});

test("generateImageEdit aborts stalled requests with a clear timeout error", async () => {
  const fetchImpl = async (_url, options) =>
    new Promise((_resolve, reject) => {
      options.signal?.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
    });

  const result = Promise.race([
    generateImageEdit({
      apiKey: "sk-test",
      productImageDataUrl: tinyPng,
      prompt: "生成主图",
      timeoutMs: 10,
      fetchImpl,
    }),
    new Promise((_resolve, reject) => {
      setTimeout(() => reject(new Error("test timed out waiting for client abort")), 80);
    }),
  ]);

  await assert.rejects(() => result, /OpenAI 图片生成超时/);
});
