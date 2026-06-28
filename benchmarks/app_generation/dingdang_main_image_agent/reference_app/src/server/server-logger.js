import { randomBytes } from "node:crypto";

const secretPattern = /(api[_-]?key|authorization|token|secret|password)/i;
const promptPattern = /(^prompt$|prompt$|Prompt$)/;

export function createRequestId() {
  return `img_${randomBytes(4).toString("hex")}`;
}

export function createServerLogger({
  sink = (line) => console.log(line),
  now = () => new Date().toISOString(),
} = {}) {
  return {
    info(event, details = {}) {
      sink(JSON.stringify({ ts: now(), level: "info", event, ...sanitizeForLog(details) }));
    },
    error(event, details = {}) {
      sink(JSON.stringify({ ts: now(), level: "error", event, ...sanitizeForLog(details) }));
    },
  };
}

export function sanitizeForLog(value, key = "") {
  if (value === null || value === undefined) return value;
  if (secretPattern.test(key)) return "[redacted]";
  if (promptPattern.test(key)) return "[omitted]";
  if (typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((item) => sanitizeForLog(item, key));

  return Object.fromEntries(
    Object.entries(value).map(([childKey, childValue]) => [
      childKey,
      sanitizeForLog(childValue, childKey),
    ]),
  );
}
