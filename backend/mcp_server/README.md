# Code a Cuisine MCP server

Makes the recipe search and USDA nutrition calculation of Code a Cuisine available
to AI assistants (Claude Desktop, Claude Code, any MCP client) via the
[Model Context Protocol](https://modelcontextprotocol.io).

No LLM runs inside the server and it needs no API keys: it uses the same `core`
code as the web API (ChromaDB vector search, USDA FoodData Central).

## Tools

| Tool | What it does |
|---|---|
| `search_recipes` | Real recipes for a list of ingredients, with optional diet, cuisine and time filters. Shows which ingredients each recipe uses and which are missing. |
| `get_recipe` | Full recipe (ingredients, steps, servings, source link) by `itemId`. |
| `get_nutrition` | Calories, protein, carbs and fat per portion from USDA data, calculated in code. Shows the USDA food each item was matched to. |

## Resources

| URI | Content |
|---|---|
| `recipes://cuisines` | Cuisines in the database with recipe counts |
| `recipes://diets` | Supported diets and the exact rule for each |

## Run locally (stdio)

Requires the vector index (`uv run python -m ingest.build_index`), then from `backend/`:

```bash
uv run python -m mcp_server.server
```

### Claude Code

```bash
claude mcp add code-a-cuisine -- uv --directory "/path/to/code-a-cuisine/backend" run python -m mcp_server.server
```

### Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config) and restart Claude Desktop.
Use the absolute path to `uv` (`which uv`), because Claude Desktop does not load your shell's PATH:

```json
{
  "mcpServers": {
    "code-a-cuisine": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["--directory", "/path/to/code-a-cuisine/backend", "run", "python", "-m", "mcp_server.server"]
    }
  }
}
```

Then ask for example: *"I have chicken, rice and spinach. Find me a gluten-free recipe and tell me its calories per portion."*

## Remote server (Streamable HTTP)

The same tools run online at `https://cuisine-api.franekkaminski.dev/mcp`
(`mcp_server/http.py`, service `mcp` in `docker-compose.yml`):

- every request needs an API key: `Authorization: Bearer <key>` (or `X-API-Key: <key>`)
- rate limit per key (default 500 requests/day, 60/minute) plus a global daily cap
- stateless JSON responses, DNS-rebinding protection via allowed Host headers

Connect from Claude Code:

```bash
claude mcp add --transport http code-a-cuisine https://cuisine-api.franekkaminski.dev/mcp \
  --header "Authorization: Bearer <your-key>"
```

Any other MCP client that supports Streamable HTTP and custom headers works the same way.

## Data and licenses

Recipes: Wikibooks Cookbook, CC BY-SA 4.0 (each result links to its source).
Nutrition: USDA FoodData Central, SR Legacy, public domain.
