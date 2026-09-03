// Calls the Vercel serverless function at /api/generate, which proxies to
// OpenRouter with the server-side OPENROUTER_API_KEY. The Vite dev server runs
// the same function locally, so this works with `npm run dev` too.
export async function generateRecipes(payload) {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CAC-Client": "web",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 429) {
      throw new Error(body.error || "You've hit the request limit. Please try again later.");
    }
    throw new Error(body.error || body.detail || `Request failed (${res.status})`);
  }

  return res.json();
}
