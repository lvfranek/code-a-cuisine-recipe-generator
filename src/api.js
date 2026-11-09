// Calls the Python backend (FastAPI). VITE_API_URL points to it,
// e.g. https://cuisine-api.franekkaminski.dev in production.
import { parseSSE } from "./sse";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

const HEADERS = {
  "Content-Type": "application/json",
  "X-CAC-Client": "web",
};

async function errorFrom(res) {
  const body = await res.json().catch(() => ({}));
  if (res.status === 429) {
    return new Error(body.error || "You've hit the request limit. Please try again later.");
  }
  return new Error(body.error || body.detail || `Request failed (${res.status})`);
}

// Sends a (resized) photo, returns { ingredients: [{ name, quantity, unit }], message? }.
export async function detectIngredients(imageBlob) {
  const res = await fetch(`${API_URL}/detect-ingredients`, {
    method: "POST",
    headers: { "Content-Type": imageBlob.type || "image/jpeg", "X-CAC-Client": "web" },
    body: imageBlob,
  });
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

// onProgress receives { event: "step" | "revision", data } while the agents work.
export async function generateRecipes(payload, { onProgress } = {}) {
  const res = await fetch(`${API_URL}/generate/stream`, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await errorFrom(res);
  if (!res.body) throw new Error("Your browser does not support streaming responses.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    const parsed = parseSSE(done ? `${buffer}\n\n` : buffer);
    buffer = parsed.rest;

    for (const { event, data } of parsed.events) {
      if (event === "result") return data;
      if (event === "error") throw new Error(data.error || "Something went wrong. Please try again.");
      onProgress?.({ event, data });
    }
    if (done) break;
  }
  throw new Error("The connection was interrupted. Please try again.");
}
