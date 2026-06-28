const defaultBaseUrl = "https://api.openai.com/v1";

import { fetchWithTimeout } from "./request-timeout.js";

const mimeExtensions = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
};

export function parseImageDataUrl(dataUrl, label = "图片") {
  const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/.exec(
    String(dataUrl || ""),
  );
  if (!match) {
    throw new Error(`${label}必须是 data:image/png、jpeg 或 webp 的 base64 Data URL`);
  }

  const [, mime, base64] = match;
  const buffer = Buffer.from(base64, "base64");
  if (!buffer.length) {
    throw new Error(`${label}内容为空`);
  }

  const extension = mimeExtensions[mime] ?? "png";
  return {
    mime,
    extension,
    fileName: `${slugLabel(label)}.${extension}`,
    blob: new Blob([buffer], { type: mime }),
  };
}

export async function generateImageEdit({
  apiKey,
  productImageDataUrl,
  referenceImageDataUrl,
  prompt,
  model = "gpt-image-2",
  size = "1024x1024",
  quality = "medium",
  outputFormat = "png",
  baseUrl = defaultBaseUrl,
  timeoutMs = 120000,
  fetchImpl = globalThis.fetch,
} = {}) {
  if (!apiKey?.trim()) {
    throw new Error("OPENAI_API_KEY 未配置，请在 .env 中填写后重试");
  }
  if (!prompt?.trim()) {
    throw new Error("Prompt 不能为空");
  }
  if (typeof fetchImpl !== "function") {
    throw new Error("当前 Node 环境缺少 fetch 实现");
  }

  const productImage = parseImageDataUrl(productImageDataUrl, "产品图");
  const body = new FormData();
  body.append("model", model);
  body.append("prompt", prompt);
  body.append("size", size);
  body.append("quality", quality);
  body.append("output_format", outputFormat);
  body.append("image", productImage.blob, productImage.fileName);

  if (referenceImageDataUrl) {
    const referenceImage = parseImageDataUrl(referenceImageDataUrl, "参考图");
    body.append("image", referenceImage.blob, referenceImage.fileName);
  }

  const endpoint = `${baseUrl.replace(/\/$/, "")}/images/edits`;
  const response = await fetchWithTimeout({
    fetchImpl,
    url: endpoint,
    timeoutMs,
    timeoutMessage: `OpenAI 图片生成超时（${Math.round(timeoutMs / 1000)} 秒），请稍后重试或降低图片数量`,
    options: {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
      },
      body,
    },
  });

  const payload = await readJson(response);
  if (!response.ok) {
    const message = payload?.error?.message || payload?.message || "未知错误";
    throw new Error(`OpenAI 图片生成失败 (${response.status}): ${message}`);
  }

  const first = payload?.data?.[0];
  if (!first?.b64_json) {
    throw new Error("OpenAI 图片生成响应缺少 b64_json");
  }

  return {
    imageDataUrl: `data:image/${outputFormat};base64,${first.b64_json}`,
    revisedPrompt: first.revised_prompt || "",
    raw: payload,
  };
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function slugLabel(label) {
  if (label === "产品图") return "product";
  if (label === "参考图") return "reference";
  if (/^[a-z0-9-]+$/i.test(label)) return label.toLowerCase();
  return "image";
}
