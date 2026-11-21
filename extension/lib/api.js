// API client: JSON calls and streamed (SSE) calls, with automatic sign-in and one retry on 401.
import { accessToken, getConfig } from "./auth.js";

export class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code; }
}

async function request(path, { method = "GET", body, signal } = {}, retry = true) {
  const cfg = await getConfig();
  if (!cfg.serverUrl) throw new ApiError("Not paired with a server yet. Open Settings.", 0, "not_paired");
  const token = await accessToken();
  const res = await fetch(cfg.serverUrl + path, {
    method, signal, credentials: "include" /* client certificates count as credentials: "omit" would withhold the mTLS cert */,
    headers: { authorization: `Bearer ${token}`, ...(body !== undefined ? { "content-type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && retry) {
    await browser.storage.session.remove("access");
    await accessToken(true);
    return request(path, { method, body, signal }, false);
  }
  return res;
}

export async function api(path, opts = {}) {
  const res = await request(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || `Request failed (${res.status})`, res.status, data.code);
  return data;
}

export const get = (path) => api(path);
export const post = (path, body = {}) => api(path, { method: "POST", body });
export const put = (path, body = {}) => api(path, { method: "PUT", body });
export const del = (path) => api(path, { method: "DELETE" });

// Server-Sent Events over a POST: yields each `data:` JSON event.
export async function* stream(path, body, signal) {
  const res = await request(path, { method: "POST", body, signal });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(data.error || `Request failed (${res.status})`, res.status, data.code);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let i;
    while ((i = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, i);
      buffer = buffer.slice(i + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data:")) {
          try { yield JSON.parse(line.slice(5).trim()); } catch { /* ignore malformed */ }
        }
      }
    }
  }
}
