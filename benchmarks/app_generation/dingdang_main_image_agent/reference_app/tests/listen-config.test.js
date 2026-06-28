import assert from "node:assert/strict";
import test from "node:test";

import {
  findLanIPv4,
  formatStartupUrls,
  resolveListenConfig,
} from "../src/server/listen-config.js";

test("resolveListenConfig listens on all interfaces by default", () => {
  const config = resolveListenConfig({});

  assert.equal(config.host, "0.0.0.0");
  assert.equal(config.port, 5173);
});

test("resolveListenConfig allows local-only override", () => {
  const config = resolveListenConfig({ HOST: "127.0.0.1", PORT: "5174" });

  assert.equal(config.host, "127.0.0.1");
  assert.equal(config.port, 5174);
});

test("findLanIPv4 returns the first non-internal IPv4 address", () => {
  const ip = findLanIPv4({
    lo0: [{ family: "IPv4", address: "127.0.0.1", internal: true }],
    en0: [{ family: "IPv4", address: "192.168.1.20", internal: false }],
  });

  assert.equal(ip, "192.168.1.20");
});

test("formatStartupUrls includes local and LAN URLs for 0.0.0.0", () => {
  const urls = formatStartupUrls(
    { host: "0.0.0.0", port: 5173 },
    { en0: [{ family: "IPv4", address: "192.168.1.20", internal: false }] },
  );

  assert.equal(urls.bindUrl, "http://0.0.0.0:5173");
  assert.equal(urls.localUrl, "http://127.0.0.1:5173");
  assert.equal(urls.lanUrl, "http://192.168.1.20:5173");
});
