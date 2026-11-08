# Project rules (copy this file to the root of your new project as `CLAUDE.md`)

This project is a GenAI / RAG system (LLMs, vector database, LangGraph, MCP).
Follow these rules in every feature you build.

## 1. Data: structure unstructured input
- Raw text and images are always converted to structured JSON before use.
- Every record has a **unique, stable `itemId`**. Other data (reviews, visit history, recipes) is matched to records through this id.
- The JSON schema is defined once as a **Pydantic model** and reused everywhere. Do not duplicate it.

## 2. LLM outputs are untrusted
- Always validate LLM output against the Pydantic schema (`model_validate_json`).
- On validation failure, run an **auto-repair step**: send the invalid output plus the error message back to an LLM, then validate again.
- Limit repair retries (max 5). Never loop forever.
- Wrap LLM and network calls with retries (e.g. `tenacity`) and log failures instead of crashing the whole batch.
- Prompts: give the model a role, the exact schema, constraints, and one example (one-shot).

## 3. Multimodal data
- Images are turned into **text captions** (vision LLM) so they can be searched and embedded with text.
- Caption prompts must say "describe only what you can see, do not invent details".
- Captions are stored in the same JSON records they belong to (matched by `itemId`).

## 4. Vector index (retrieval layer)
- Build the retrieval layer as its own reusable component, independent of the generation model.
- Use **one collection per modality** (e.g. `restaurant_articles` for text, `food_images` for images). Use a modality-appropriate embedding model for each (text: Sentence-Transformers, images: CLIP).
- **L2-normalize** all embeddings so cosine similarity works.
- Turn every record into a document with: retrieval text, a **unique `doc_id`**, and **metadata** (e.g. cuisine, location, source, recipe_id) so searches can be filtered.
- Write with `upsert` and explicit ids, so re-running the pipeline never creates duplicates.
- **Persist** the index to disk (`persist_directory`) and reset it deliberately before a full rebuild.
- Match images to records by id, never by list position alone. Check that the number of images equals the number of records before zipping them together.

## 5. Retrieval (search layer)
- Use **hybrid retrieval**: vector similarity (top-k) combined with metadata filters (`where`), so results match both meaning and business rules (location, cuisine, source).
- Embed every query with the **same model that built the index** (same dimensions, same normalization).
- **Fail early**: before searching, check that the database directory exists and the collections are not empty. Raise a clear error instead of returning empty results silently.
- Handle empty results explicitly (e.g. a filter value that does not exist in the data) and tell the user.
- Keep small helper functions for unwrapping and printing results, so retrieval code stays clean.
- Filter values must exist in the metadata. Check real values before hardcoding a filter.

## 5b. Multimodal fusion and ranking
- Scores from different embedding models (e.g. text vs. CLIP) are **not comparable**. Convert distance to similarity (`1 - distance`) and **normalize per modality** before combining.
- Combine with a **weighted sum** (`w_text * text_score + w_img * img_score`). Make the weights parameters, not constants, and document the defaults.
- Retrieve candidates (top-k) from each modality first, then fuse and cut to the final top-n.
- Min-max normalization is **relative**: the best hit of a modality always gets 1.0, even if it is a poor match (e.g. a pancake image for "sushi"). Also check the **raw similarity** and drop or flag hits below a minimum threshold.
- Test fusion with several weight settings (text-heavy and image-heavy) and inspect the ranked output yourself.

## 5c. Multi-agent design
- One agent = one responsibility. Split the pipeline into specialized agents (e.g. user profile, retriever, trend, style, nutrition, recommendation). Each downstream agent uses the output of the one before.
- Every agent has a **role** (short title), a **goal** (one clear outcome) and a **backstory** (expertise and tone). Keep them in one config dict per agent.
- Every task has a **description** (what to do, as a bullet list), an **expected_output** (exact format, e.g. JSON keys) and the **agent** that owns it.
- Build system prompts from the config with one helper function, so agents stay consistent.
- Only the retriever agent queries the vector database. Other agents work on its results.
- Ask for evidence: tasks should require specific examples from the data to support each insight.

## 5d. Multi-agent workflow (orchestration)
- Use a **shared state** (TypedDict or dict) with one field per result: input, user_profile, retrieved items, each analysis, final_recommendations, `workflow_step`.
- Each node is a small function: reads state, calls one agent, writes its own state field, returns state. One node writes only its own fields.
- Hybrid workflow: run dependent steps **sequentially** (profile → retrieval → synthesis) and independent steps **in parallel** (trends, styles, nutrition). Give each parallel node its own copy of the state and merge the results afterwards.
- Set `workflow_step` after each phase for progress tracking and debugging.
- Wrap each node in try/except and store an `error` field, so one failing agent does not crash the workflow. Check for `error` before the synthesis step.
- Parse agent output with `json.loads` only inside try/except, or validate with Pydantic (see section 2).
- The retriever node must query the **real vector database** (section 4/5). Never let an LLM invent ("simulate") retrieval results in production.
- Read the API key from the environment (`OPENAI_API_KEY`), never from code. Keep the model name in one constant.
- Test the full workflow with several different user personas and evaluate the output (dietary rules respected? cuisines match?).

## 5e. MCP (Model Context Protocol)
- Split the system into an **MCP server** (tools, resources) and an **MCP host/client** (agent, UI). The host launches the server as a subprocess (stdio) and discovers tools at runtime with `list_tools()`. Do not hardcode tool lists.
- **Tools** do actions or lookups (e.g. `get_restaurant_info`, `recommend_by_vibe`, `get_review`). Each tool has a clear name, a short description and typed arguments, and returns JSON.
- **Resources** expose read-only data through a URI (e.g. `culinary-map://california`).
- **Roots**: implement `list_roots` and allow the server only the project directory it needs.
- **Sampling**: if the server needs an LLM, it asks the client (`handle_sampling`). The server holds no LLM keys.
- Search tools use two passes: structured fields first (tags, metadata), then raw text, and return both.
- ReAct loop in the host: the LLM returns tool calls, the host executes them through the MCP server, feeds the results back, and repeats until the LLM answers. Set a maximum number of loop steps.
- The system prompt names the agent, lists every tool with a "use it when ..." rule, and says: never invent facts, always use a tool for data.
- Read project id and API keys from environment variables. The UI (Gradio) shows a "Thinking..." placeholder while the agent works.
- Check tool results for errors and empty output before the LLM uses them.

## 6. Safe file and database writes
- Create a **backup before overwriting** any data file or collection.
- Ask for explicit confirmation before add / edit / delete actions.
- Validate user input (e.g. record index) before using it.
- Never delete or overwrite data silently.

## 7. Quality
- Keep functions small: one prompt-builder, one LLM call, one validator, one repair step.
- Write unit tests for new features. Mock user input and external services where possible.
- Never hardcode API keys. Read secrets from environment variables and keep `.env` out of git.
- Before calling a task done, run the tests and report the real result.
