// Calls the recipe backend.
// - VITE_API_URL set (e.g. http://localhost:8000): the Python backend's /generate.
// - VITE_API_URL empty: the old Vercel function at /api/generate (also runs
//   locally through the Vite dev server).
const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
const GENERATE_URL = API_URL ? `${API_URL}/generate` : "/api/generate";

export async function generateRecipes(payload) {
  const res = await fetch(GENERATE_URL, {
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
