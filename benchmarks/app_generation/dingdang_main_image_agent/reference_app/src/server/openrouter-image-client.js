const defaultBaseUrl = "https://openrouter.ai/api/v1";

import { fetchWithTimeout } from "./request-timeout.js";

export function toInputReference(dataUrl, label = "图片") {
  if (!/^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(String(dataUrl || ""))) {
    throw new Error(`${label}必须是 data:image/png、jpeg 或 webp 的 base64 Data URL`);
  }
  return {
    type: "image_url",
    image_url: { url: dataUrl },
  };
}

export async function generateOpenRouterImage({
  apiKey,
  productImageDataUrl,
  referenceImageDataUrl,
  prompt,
  model = "openai/gpt-image-1",
  size = "1024x1024",
  quality = "high",
  outputFormat = "png",
  baseUrl = defaultBaseUrl,
  timeoutMs = 120000,
  fetchImpl = globalThis.fetch,
} = {}) {
  if (!apiKey?.trim()) {
    throw new Error("OPENROUTER_API_KEY 未配置，请在 .env 中填写后重试");
  }
  if (!prompt?.trim()) {
    throw new Error("Prompt 不能为空");
  }
  if (typeof fetchImpl !== "function") {
    throw new Error("当前 Node 环境缺少 fetch 实现");
  }

  const inputReferences = [toInputReference(productImageDataUrl, "产品图")];
  if (referenceImageDataUrl) {
    inputReferences.push(toInputReference(referenceImageDataUrl, "参考图"));
  }

  const response = await fetchWithTimeout({
    fetchImpl,
    url: `${baseUrl.replace(/\/$/, "")}/images`,
    timeoutMs,
    timeoutMessage: `OpenRouter 图片生成超时（${Math.round(timeoutMs / 1000)} 秒），请稍后重试或降低图片数量`,
    options: {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        prompt,
        size,
        quality,
        output_format: outputFormat,
        input_references: inputReferences,
      }),
    },
  });

  const payload = await readJson(response);
  if (!response.ok) {
    const message = payload?.error?.message || payload?.message || "未知错误";
    throw new Error(`OpenRouter 图片生成失败 (${response.status}): ${message}`);
  }

  const first = payload?.data?.[0];
  const b64 = first?.b64_json || first?.image_base64;
  const url = first?.url;
  if (b64) {
    return {
      imageDataUrl: `data:image/${outputFormat};base64,${b64}`,
      revisedPrompt: first.revised_prompt || "",
      usage: payload.usage || null,
      raw: payload,
    };
  }
  if (url) {
    return {
      imageDataUrl: url,
      revisedPrompt: first.revised_prompt || "",
      usage: payload.usage || null,
      raw: payload,
    };
  }

  throw new Error("OpenRouter 图片生成响应缺少 b64_json 或 url");
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}
