import { existsSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const TOOL_IMPORTS = {
  ask_api_catalog: {
    module: "src/tools/ask_api_catalog.mjs",
    exportName: "askApiCatalog",
  },
  select_tools_for_task: {
    module: "src/tools/select_tools_for_task.mjs",
    exportName: "selectToolsForTask",
  },
  list_domain_apis: {
    module: "src/tools/list_domain_apis.mjs",
    exportName: "listDomainApis",
  },
  get_api_asset_card: {
    module: "src/tools/get_api_asset_card.mjs",
    exportName: "getApiAssetCard",
  },
  probe_api_sample: {
    module: "src/tools/probe_api_sample.mjs",
    exportName: "probeApiSampleTool",
  },
  probe_api_batch: {
    module: "src/tools/probe_api_sample.mjs",
    exportName: "probeApiSampleTool",
  },
};

function clamp(value, min, max, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.max(min, Math.min(max, Math.floor(numeric))) : fallback;
}

function rowsFromProbeResult(result) {
  return result && result.response && Array.isArray(result.response.top) ? result.response.top : [];
}

function retryableProbeResult(result) {
  const state = String(result && result.status && result.status.state || "");
  return state === "timeout" || state === "network_error";
}

async function probeApiBatch(fn, args) {
  const apiId = String(args.api_id || "").trim();
  const items = Array.isArray(args.items) ? args.items.slice(0, 50) : [];
  const concurrency = clamp(args.concurrency, 1, 10, 5);
  const retry = clamp(args.retry, 0, 1, 1);
  const timeoutMs = clamp(args.timeout_ms, 1000, 30000, 8000);
  const topPerItem = clamp(args.top_per_item, 1, 50, 1);
  const results = new Array(items.length);
  let cursor = 0;

  async function runItem(item, position) {
    const correlationId = String(item && item.correlation_id || position);
    const params = item && item.params && typeof item.params === "object" ? item.params : {};
    let attempts = 0;
    let response = null;
    let error = "";
    while (attempts <= retry) {
      attempts += 1;
      try {
        response = await fn({ api_id: apiId, params, top: topPerItem, timeout_ms: timeoutMs });
        if (!retryableProbeResult(response) || attempts > retry) break;
      } catch (caught) {
        error = String(caught && caught.message ? caught.message : caught);
        if (attempts > retry) break;
      }
    }
    const state = String(response && response.status && response.status.state || "");
    const rows = rowsFromProbeResult(response);
    const status = state === "ok" && rows.length > 0
      ? "success"
      : state === "ok"
        ? "empty"
        : "failed";
    results[position] = {
      correlation_id: correlationId,
      status,
      attempts,
      rows,
      response,
      error,
    };
  }

  async function runner() {
    while (true) {
      const position = cursor;
      cursor += 1;
      if (position >= items.length) return;
      await runItem(items[position], position);
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, Math.max(items.length, 1)) }, () => runner()));
  const summary = { requested: items.length, success: 0, empty: 0, failed: 0 };
  for (const item of results) summary[item.status] += 1;
  return {
    kind: "api_probe_batch_result",
    api_id: apiId,
    concurrency,
    retry,
    timeout_ms: timeoutMs,
    top_per_item: topPerItem,
    summary,
    items: results,
  };
}

function write(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let body = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", chunk => {
      body += chunk;
    });
    process.stdin.on("end", () => resolve(body));
    process.stdin.on("error", reject);
  });
}

function resolveModule(specPackRoot, relPath) {
  const direct = path.join(specPackRoot, relPath);
  if (existsSync(direct)) return direct;
  if (direct.endsWith(".mjs")) {
    const tsPath = direct.slice(0, -4) + ".ts";
    if (existsSync(tsPath)) return tsPath;
  }
  return direct;
}

async function main() {
  const raw = await readStdin();
  const request = raw.trim() ? JSON.parse(raw) : {};
  const specPackRoot = path.resolve(String(request.spec_pack_root || process.env.DB_ARCHAEOLOGIST_SPEC_PACK || ""));
  const tool = String(request.tool || "");
  const args = request.args && typeof request.args === "object" ? request.args : {};
  const liveEnabled = process.env.DBA_LIVE_PROBE === "1";

  if (!specPackRoot || !existsSync(specPackRoot)) {
    write({ ok: false, status: "degraded", reason: "spec_pack_not_found", spec_pack_root: specPackRoot });
    return;
  }
  if (!Object.prototype.hasOwnProperty.call(TOOL_IMPORTS, tool)) {
    write({ ok: false, status: "blocked", reason: "tool_not_allowed", tool });
    return;
  }
  if ((tool === "probe_api_sample" || tool === "probe_api_batch") && !liveEnabled) {
    write({ ok: false, status: "blocked", reason: "live_probe_disabled", tool, live_enabled: false });
    return;
  }

  process.env.REGISTRY_ROOT = specPackRoot;
  process.env.SPEC_PACK_ROOT = specPackRoot;
  process.chdir(specPackRoot);

  const target = TOOL_IMPORTS[tool];
  const modulePath = resolveModule(specPackRoot, target.module);
  const mod = await import(pathToFileURL(modulePath).href);
  const fn = mod[target.exportName];
  if (typeof fn !== "function") {
    write({ ok: false, status: "error", reason: "tool_export_missing", tool, export_name: target.exportName });
    return;
  }
  const payload = tool === "probe_api_batch" ? await probeApiBatch(fn, args) : await fn(args);
  write({ ok: true, status: "ok", tool, payload });
}

main().catch(error => {
  write({
    ok: false,
    status: "error",
    reason: "worker_error",
    error: String(error && error.message ? error.message : error),
  });
  process.exit(1);
});
