# 🍳 Code a Cuisine

Tell the app what's in your kitchen and it gives you three recipes you can cook
with what you already have — full ingredient lists and plain, step-by-step
instructions written so anyone can follow them.

![Code a Cuisine](public/code-a-cuisine.jpeg)

## 🎞️ Live Demo

**[code-a-cuisine-three.vercel.app](https://code-a-cuisine-three.vercel.app/)**

## 🚀 Features

**Recipe generator**
- Two-step guided flow: add your ingredients (name / quantity / unit), then set
  your preferences.
- Tailor results by **portions**, **number of people**, **cooking time**
  (quick / medium / complex), **cuisine**, and **dietary needs**
  (vegan, vegetarian, keto, gluten-free, dairy-free, low-carb, paleo).
- `Any` cuisine option when you don't mind what style it is.
- Every preference is required before **Generate Recipes** unlocks, with an
  inline hint telling you what's missing.
- Returns exactly three recipes, each with a description, per-portion nutrition
  (calories / protein / carbs / fat), a full ingredient list, and 6–10
  numbered instruction steps in simple everyday language.

**Recipe Book**
- Save any generated recipe with one click; it's kept in the browser via
  `localStorage` (no account needed).
- Browse saved recipes with filters for cuisine, cooking time, and dietary tag,
  plus pagination.
- Remove a recipe by toggling **Saved** off from its card.

**Under the hood**
- Recipe generation runs through a **Vercel serverless function**
  (`api/generate.js`) so the API key never reaches the browser.
- The function retries up to 3× on rate limits, transient errors, or malformed
  model output, and surfaces a readable error in the UI if it still fails.
- **Abuse-hardened** for public use: server-side input validation and per-IP /
  global rate limiting on `/api/generate` (see [Security & limits](#-security--limits)).
- The Vite dev server runs the same `/api` function locally with the same
  request/response shape Vercel uses — **works locally ⇒ works on Vercel**, no
  extra tooling.
- Responsive layout down to small mobile widths; respects
  `prefers-reduced-motion`.

## ⌨️ Tech Stack

| Area        | Choice                                              |
| ----------- | -------------------------------------------------- |
| UI          | React 19                                           |
| Build tool  | Vite 8                                             |
| Language    | JavaScript (ESM)                                   |
| Styling     | Plain CSS with design tokens (no framework)        |
| AI          | [OpenRouter](https://openrouter.ai) — model `minimax/minimax-m3:free` |
| Backend     | Vercel Serverless Functions (`/api`)               |
| Persistence | Browser `localStorage`                             |
| Rate limit  | Upstash Redis (optional) with in-memory fallback   |
| Linting     | ESLint 10 (flat config)                            |

## 🏗️ How It Works

```
Browser (React)
   │  POST /api/generate  { ingredients, portions, people, cookingTime, cuisines, dietPreferences }
   ▼
/api/generate.js  (Vercel function — locally: Vite dev middleware)
   │  validates + rate-limits the request
   │  builds a prompt, calls OpenRouter with OPENROUTER_API_KEY (server-side)
   │  parses + normalises the model's JSON, retries on failure
   ▼
{ recipes: [ { name, description, cookTime, cuisine, dietTags,
               portions, nutrition, ingredients[], instructions[] } × 3 ] }
```

The key stays server-side in both environments. Locally, a small plugin in
[`vite.config.js`](vite.config.js) mounts everything in `/api` as real
endpoints during `npm run dev`, mirroring Vercel's runtime.

## 📁 Project Structure

```
api/
  generate.js          Serverless function: validation, rate limit, OpenRouter call, retries
lib/
  validate.js          Request-body validation + normalisation (shared, server-side)
  ratelimit.js         Per-IP + global rate limiting (Upstash Redis or in-memory)
src/
  api.js               Front-end wrapper around POST /api/generate
  cookbook.js           localStorage-backed Recipe Book store
  App.jsx               App shell, routing between screens, generate flow
  App.css               All styles + design tokens
  components/
    StepIngredients.jsx  Step 1 — add ingredients
    StepPreferences.jsx  Step 2 — preferences + validation
    LoadingScreen.jsx    Generation loading state
    ResultsPage.jsx      The three generated recipes
    RecipeCard.jsx       Recipe card (used in results and the Recipe Book)
    CookbookPage.jsx     Recipe Book — filters + pagination
    LogoIcon.jsx
  pages/
    PrivacyPage.jsx
    TermsPage.jsx
vite.config.js          Vite config + local /api dev middleware
```

## 🔑 Environment

Create a `.env` file in the project root (copy [`.env.example`](.env.example)):

```bash
OPENROUTER_API_KEY=sk-or-...
```

Get a free key at <https://openrouter.ai/keys>. It's used **only** by
`api/generate.js` on the server — it is never bundled into the client.

**Optional:** rate limiting works out of the box (in-memory). For limits shared
across serverless instances, add an [Upstash Redis](https://upstash.com/) store
(Vercel → *Storage*, free tier) and set `UPSTASH_REDIS_REST_URL` +
`UPSTASH_REDIS_REST_TOKEN`. See [`.env.example`](.env.example) for the tunable
`RATELIMIT_*` values.

## 🚦 Getting Started

**Prerequisites:** Node.js 18+ (developed on Node 24).

```bash
npm install
cp .env.example .env      # then paste your OpenRouter key
npm run dev
```

Open <http://localhost:5173/>. Editing any source file hot-reloads the app.
Because the dev server also runs `/api`, recipe generation works the same
locally as in production.

## 📜 Available Scripts

| Command           | What it does                                            |
| ----------------- | ------------------------------------------------------ |
| `npm run dev`     | Start the dev server (with the local `/api` function)  |
| `npm run build`   | Production build into `dist/`                          |
| `npm run preview` | Serve the built `dist/` (static only — no `/api`)      |
| `npm run lint`    | Run ESLint over the project                            |

## ☁️ Deploying to Vercel

1. Import the repository into Vercel (framework preset: **Vite**).
2. Add an environment variable **`OPENROUTER_API_KEY`** under
   *Project → Settings → Environment Variables*.
3. Deploy. Vercel automatically serves `/api/generate.js` as a serverless
   function — no config file needed.
4. *(Optional)* Add an Upstash Redis store and its env vars for shared rate
   limiting (see [Environment](#-environment)).

## 🔒 Security & Limits

`/api/generate` is a public endpoint, so it's hardened server-side:

- **Input validation** ([`lib/validate.js`](lib/validate.js)): ≤ 20 ingredients,
  name ≤ 50 chars (control chars stripped), quantity `0–100000`, and every
  enum (`unit` / `cuisine` / `diet` / `cookingTime`) checked against a fixed
  allow-list. 10 KB body cap. `POST` + same-origin only.
- **Rate limiting** ([`lib/ratelimit.js`](lib/ratelimit.js)): 15/day + 5/min per
  IP, 300/day overall; `429` with `Retry-After` when exceeded. IPs are hashed,
  never stored raw.

User input only becomes text inside the model prompt — no `eval`, shell,
filesystem or database — and React escapes all rendered output.

## 📝 Notes & Limitations

- **Free model:** `minimax/minimax-m3:free` is rate-limited on OpenRouter's free
  tier and occasionally returns imperfect JSON — the function retries, but under
  heavy use a request can still fail. Swap `MODEL` in
  [`api/generate.js`](api/generate.js) for a paid model if you need reliability.
- **Recipe Book is per-browser:** saved recipes live in `localStorage` on one
  device. Clearing site data or switching browsers loses them. Making it
  cross-device would require a real backend/database.
- **`npm run preview`** serves only the static build, so recipe generation won't
  work there — use `npm run dev` or a Vercel deployment.

## 📚 Additional Resources

- [Vite documentation](https://vite.dev/)
- [OpenRouter documentation](https://openrouter.ai/docs)
- [Vercel Functions documentation](https://vercel.com/docs/functions)
