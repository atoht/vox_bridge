import type { StreamConfig } from "./types";

const backendUrl = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8000";

export function buildWsUrl(): string {
  // WebSocket 协议需要随 HTTP/HTTPS 自动切换。
  const url = new URL(backendUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/translate";
  return url.toString();
}

export async function requestTts(text: string, language: StreamConfig["target_language"]) {
  const response = await fetch(`${backendUrl}/api/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language }),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.blob();
}
