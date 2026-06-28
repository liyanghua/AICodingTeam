import { createReadStream, existsSync, readFileSync } from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { networkInterfaces } from "node:os";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { generateImageFromProvider, resolveImageProviderConfig } from "./image-provider.js";
import { formatStartupUrls, resolveListenConfig } from "./listen-config.js";
import { createRequestId, createServerLogger } from "./server-logger.js";

const currentFile = fileURLToPath(import.meta.url);
const projectRoot = resolve(dirname(currentFile), "../..");
const publicRoot = join(projectRoot, "public");
const sharedRoot = join(projectRoot, "src/shared");
const logger = createServerLogger();

loadEnvFile();

const listenConfig = resolveListenConfig(process.env);

export function createServer() {
  return createHttpServer(async (request, response) => {
    try {
      const url = new URL(request.url, `http://${request.headers.host || "localhost"}`);

      if (request.method === "GET" && url.pathname === "/api/health") {
        const providerConfig = resolveImageProviderConfig(process.env);
        return sendJson(response, 200, {
          ok: true,
          provider: providerConfig.provider,
          hasApiKey: Boolean(providerConfig.apiKey),
          imageModel: providerConfig.model,
          imageSize: providerConfig.size,
          imageQuality: providerConfig.quality,
          imageOutputFormat: providerConfig.outputFormat,
        });
      }

      if (request.method === "POST" && url.pathname === "/api/images/generate") {
        const requestId = createRequestId();
        const startedAt = Date.now();
        const body = await readJson(request);
        const providerConfig = resolveImageProviderConfig(process.env);
        logger.info("image.generate.start", {
          requestId,
          provider: providerConfig.provider,
          model: body.options?.model || providerConfig.model,
          size: body.options?.size || providerConfig.size,
          quality: body.options?.quality || providerConfig.quality,
          outputFormat: body.options?.outputFormat || providerConfig.outputFormat,
          hasProductImage: Boolean(body.productImageDataUrl),
          hasReferenceImage: Boolean(body.referenceImageDataUrl),
          promptLength: String(body.prompt || "").length,
          timeoutMs: body.options?.timeoutMs || providerConfig.timeoutMs,
        });
        const result = await generateImageFromProvider({
          env: process.env,
          request: body,
        });
        logger.info("image.generate.success", {
          requestId,
          provider: result.provider,
          elapsedMs: Date.now() - startedAt,
          hasImageDataUrl: Boolean(result.imageDataUrl),
          hasRevisedPrompt: Boolean(result.revisedPrompt),
          usage: result.usage,
        });
        return sendJson(response, 200, result);
      }

      if (request.method !== "GET" && request.method !== "HEAD") {
        return sendJson(response, 405, { error: "Method not allowed" });
      }

      return serveStatic(url.pathname, response);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const status = /API_KEY|Prompt|data:image|不能为空|IMAGE_PROVIDER/.test(message) ? 400 : 500;
      logger.error("request.error", {
        method: request.method,
        url: request.url,
        status,
        errorName: error?.name,
        message,
      });
      return sendJson(response, status, { error: message });
    }
  });
}

function serveStatic(pathname, response) {
  const route = pathname === "/" ? "/index.html" : decodeURIComponent(pathname);
  const root = route.startsWith("/src/shared/") ? projectRoot : publicRoot;
  const filePath = safeJoin(root, route.startsWith("/src/shared/") ? route.slice(1) : route);

  if (!filePath || !existsSync(filePath)) {
    return sendJson(response, 404, { error: "Not found" });
  }

  response.writeHead(200, {
    "Content-Type": contentType(filePath),
    "Cache-Control": "no-store",
  });
  createReadStream(filePath).pipe(response);
}

function safeJoin(root, requestedPath) {
  const target = normalize(join(root, requestedPath.replace(/^\/+/, "")));
  return target.startsWith(root) ? target : null;
}

function sendJson(response, status, payload) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(payload));
}

function readJson(request) {
  return new Promise((resolveJson, reject) => {
    let data = "";
    request.on("data", (chunk) => {
      data += chunk;
      if (data.length > 25 * 1024 * 1024) {
        reject(new Error("请求体过大"));
        request.destroy();
      }
    });
    request.on("end", () => {
      try {
        resolveJson(data ? JSON.parse(data) : {});
      } catch {
        reject(new Error("请求 JSON 格式错误"));
      }
    });
    request.on("error", reject);
  });
}

function loadEnvFile() {
  const envPath = join(projectRoot, ".env");
  if (!existsSync(envPath)) return;

  const lines = readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim().replace(/^['"]|['"]$/g, "");
    if (key && process.env[key] === undefined) process.env[key] = value;
  }
}

function contentType(filePath) {
  const ext = extname(filePath);
  return (
    {
      ".html": "text/html; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".json": "application/json; charset=utf-8",
      ".png": "image/png",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".webp": "image/webp",
      ".svg": "image/svg+xml",
    }[ext] || "application/octet-stream"
  );
}

if (process.argv[1] === currentFile) {
  createServer().listen(listenConfig.port, listenConfig.host, () => {
    logger.info("server.start", formatStartupUrls(listenConfig, networkInterfaces()));
  });
}
