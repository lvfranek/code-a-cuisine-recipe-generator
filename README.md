# 🍳 Code a Cuisine

An AI-powered culinary platform. Intelligent recipe generation, automated ingredient sourcing, and workflow automation — generate recipes based on the groceries you already have.

## ⌨️ Technologies

- `React`
- `Vite`
- `JavaScript`
- `CSS`
- `OpenRouter` (model: `minimax/minimax-m3:free`)
- `Vercel Serverless Functions`

## 🚀 Features

- Generate recipes with an LLM (via OpenRouter) from the groceries you already have
- Tailor results by portions, cooking time, cuisine, and dietary needs
- Save recipes to a personal Recipe Book (stored in the browser via `localStorage`)
- Clean, responsive recipe card interface

## 🎞️ Live Demo

[code-a-cuisine-three.vercel.app](https://code-a-cuisine-three.vercel.app/)

## 🔑 Environment

Recipe generation calls OpenRouter through a serverless function ([`api/generate.js`](api/generate.js)),
so the API key stays on the server and is **never** shipped to the browser.

Create a `.env` file in the project root (copy [`.env.example`](.env.example)):

```bash
OPENROUTER_API_KEY=sk-or-...
```

Get a key at <https://openrouter.ai/keys>. For deployment, set the same variable in
**Vercel → Project → Settings → Environment Variables**, then redeploy.

## 🚦 Running the Project

This project was generated using [Vite](https://vite.dev/).

### Development server

```bash
npm install
npm run dev
```

Open `http://localhost:5173/`. The Vite config runs the functions in `/api`
locally with the exact same request/response shape Vercel uses — so if recipe
generation works with `npm run dev`, it works on Vercel with no extra steps
(same `api/*.js` files, same `OPENROUTER_API_KEY`).

### Building

To build the project run:

```bash
npm run build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

### Preview the production build

```bash
npm run preview
```

### Linting

To lint the project, run:

```bash
npm run lint
```

## 📚 Additional Resources

For more information on the tools used in this project, visit the [Vite documentation](https://vite.dev/), the [OpenRouter documentation](https://openrouter.ai/docs), and the [Vercel Functions documentation](https://vercel.com/docs/functions).
