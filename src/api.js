// Calls the Vercel serverless function at /api/generate, which proxies to
// OpenRouter with the server-side OPENROUTER_API_KEY. Run `vercel dev` locally
// so this route exists (plain `vite` has no /api routes).
export async function generateRecipes(payload) {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.error || `Request failed (${res.status})`);
  }

  return res.json();
}
