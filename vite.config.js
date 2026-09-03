import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

// Runs the serverless functions in /api during `vite dev`, mirroring Vercel's
// runtime. This means `npm run dev` and a Vercel deploy behave identically:
// the same api/*.js files, the same request/response shape, the same env vars.
// Nothing here runs in production — Vercel serves /api with its own runtime.
function vercelApiDev(env) {
  return {
    name: 'vercel-api-dev',
    configureServer(server) {
      // Make .env values (e.g. OPENROUTER_API_KEY) visible to the handlers.
      for (const [key, value] of Object.entries(env)) {
        if (process.env[key] === undefined) process.env[key] = value
      }

      server.middlewares.use(async (req, res, next) => {
        if (!req.url || !req.url.startsWith('/api/')) return next()

        const route = req.url.split('?')[0].replace(/\/+$/, '')
        const file = resolve(process.cwd(), `${route.slice(1)}.js`)

        let handler
        try {
          handler = (await server.ssrLoadModule(file)).default
        } catch {
          return next()
        }
        if (typeof handler !== 'function') return next()

        // Buffer the request body and parse JSON, like Vercel does.
        const chunks = []
        for await (const chunk of req) chunks.push(chunk)
        const raw = Buffer.concat(chunks).toString('utf8')
        try {
          req.body = raw ? JSON.parse(raw) : {}
        } catch {
          req.body = raw
        }

        // Adapt the Node response to the Vercel-style res.status().json() API.
        res.status = (code) => {
          res.statusCode = code
          return res
        }
        res.json = (payload) => {
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(payload))
          return res
        }
        res.send = (body) => {
          res.end(body)
          return res
        }

        try {
          await handler(req, res)
        } catch (err) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ error: 'Handler crashed', detail: String(err) }))
        }
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), vercelApiDev(env)],
  }
})
