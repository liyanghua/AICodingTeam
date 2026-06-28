export function resolveListenConfig(env = process.env) {
  return {
    host: env.HOST || "0.0.0.0",
    port: parsePort(env.PORT),
  };
}

export function findLanIPv4(networks = {}) {
  for (const entries of Object.values(networks)) {
    for (const entry of entries || []) {
      if (entry.family === "IPv4" && !entry.internal && entry.address) {
        return entry.address;
      }
    }
  }
  return null;
}

export function formatStartupUrls(config, networks = {}) {
  const localUrl = `http://127.0.0.1:${config.port}`;
  const lanAddress = config.host === "0.0.0.0" ? findLanIPv4(networks) : null;
  return {
    bindUrl: `http://${config.host}:${config.port}`,
    localUrl,
    lanUrl: lanAddress ? `http://${lanAddress}:${config.port}` : null,
  };
}

function parsePort(value) {
  const parsed = Number(value || 5173);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 5173;
}
