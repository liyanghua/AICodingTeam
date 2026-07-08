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
};

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
  if (tool === "probe_api_sample" && !liveEnabled) {
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
  const payload = await fn(args);
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
