import { generateImageEdit } from "./openai-image-client.js";
import { generateOpenRouterImage } from "./openrouter-image-client.js";

export function resolveImageProviderConfig(env = process.env) {
  const provider = normalizeProvider(env.IMAGE_PROVIDER || "openai");
  const shared = {
    provider,
    outputFormat:
      env[provider === "openrouter" ? "OPENROUTER_IMAGE_OUTPUT_FORMAT" : "OPENAI_IMAGE_OUTPUT_FORMAT"] ||
      "png",
  };

  if (provider === "openrouter") {
    return {
      ...shared,
      apiKey: env.OPENROUTER_API_KEY,
      model: env.OPENROUTER_IMAGE_MODEL || "openai/gpt-image-1",
      size: env.OPENROUTER_IMAGE_SIZE || "1024x1024",
      quality: env.OPENROUTER_IMAGE_QUALITY || "high",
      baseUrl: env.OPENROUTER_API_BASE_URL,
      timeoutMs: parseTimeout(env.IMAGE_REQUEST_TIMEOUT_MS),
    };
  }

  return {
    ...shared,
    apiKey: env.OPENAI_API_KEY,
    model: env.OPENAI_IMAGE_MODEL || "gpt-image-2",
    size: env.OPENAI_IMAGE_SIZE || "1024x1024",
    quality: env.OPENAI_IMAGE_QUALITY || "medium",
    baseUrl: env.OPENAI_API_BASE_URL,
    timeoutMs: parseTimeout(env.IMAGE_REQUEST_TIMEOUT_MS),
  };
}

export async function generateImageFromProvider({
  env = process.env,
  request,
  fetchImpl = globalThis.fetch,
} = {}) {
  const config = resolveImageProviderConfig(env);
  const options = request?.options || {};
  const args = {
    apiKey: config.apiKey,
    productImageDataUrl: request?.productImageDataUrl,
    referenceImageDataUrl: request?.referenceImageDataUrl,
    prompt: request?.prompt,
    model: options.model || config.model,
    size: options.size || config.size,
    quality: options.quality || config.quality,
    outputFormat: options.outputFormat || config.outputFormat,
    baseUrl: config.baseUrl || undefined,
    timeoutMs: options.timeoutMs || config.timeoutMs,
    fetchImpl,
  };

  const result =
    config.provider === "openrouter"
      ? await generateOpenRouterImage(args)
      : await generateImageEdit(args);

  return {
    ...result,
    provider: config.provider,
  };
}

function normalizeProvider(provider) {
  const normalized = String(provider).trim().toLowerCase();
  if (normalized === "openrouter" || normalized === "openai") return normalized;
  throw new Error(`不支持的 IMAGE_PROVIDER: ${provider}`);
}

function parseTimeout(value) {
  const parsed = Number(value || 120000);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 120000;
}
