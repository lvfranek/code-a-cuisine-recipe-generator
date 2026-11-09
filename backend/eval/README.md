# Evaluation: does the diet checker work?

**Question:** How often do generated recipes break the diet the user asked for
(e.g. honey in a "Vegan" recipe), and what do the diet checker agent and the
diet rules change?

```bash
uv run python -m eval.run            # ~10 cents, ~5 minutes
uv run python -m eval.run --limit 3  # quick check
```

## Method

- **36 requests** in [cases.json](cases.json), covering all 7 diets and two combinations.
  Almost every request contains a **trap**: an ingredient of the user that breaks the
  requested diet. 30 traps are obvious (honey for Vegan, soy sauce for Gluten-Free, rice
  for Keto), 6 are **hidden** in ready-made products (pesto has parmesan, kimchi has fish
  sauce, marshmallows have gelatin, stock cubes and naan contain wheat, Caesar dressing has
  anchovy).
- Every request runs through the real workflow (retrieval, chef agent, nutrition) **twice**:
  without and with the diet checker agent (rule check + LLM critic + up to 2 revisions).
- Every recipe (3 per request) is graded by an **independent judge**: `anthropic/claude-haiku-5.5`,
  a different model family than the app's `google/gemini-2.5-flash-lite`, with the same diet
  definitions. The deterministic diet rules are reported too, but they share logic with the
  checker and are therefore not an independent measure.
- Metrics: share of recipes breaking a requested diet, share of recipes **labelled** with
  the diet while breaking it, time, revision rounds, LLM cost per request.

## Results

Latest run: [RESULTS.md](RESULTS.md). How we got there, one change at a time
(each row = one full run, single run per request):

| Version | Change | Breaking the diet: without → with checker | Wrongly labelled (with checker) | Time with checker | Cost per request |
|---|---|---|---|---|---|
| v1 | Baseline: chef + diet checker | **47 % → 21 %** (30 requests) | 43 % → **6 %** | 12.5 s | $0.0021 |
| v2 | Chef is told *before* cooking which of the user's ingredients break the diet, with a substitute | 0 % → 1 % | 1 % | 9.2 s | $0.0016 |
| v3 | Diet rules understand substitutes ("olive oil *(instead of butter)*", zucchini noodles); fewer false alarms and needless revisions | 0 % → 0 % | 0 % | 7.4 s | $0.0011 |
| v4 | +6 requests with **hidden** traps (36 requests) | **6 % → 1 %** | 1 % | 7.6 s | $0.0012 |
| v5 | Rules know ready-made products with hidden ingredients (pesto, kimchi, stock cubes …) | 0 % → 1 %\* | 1 %\* | 7.7 s | $0.0011 |

\* The one remaining case is a judge error: it flagged eggs for Paleo, which the
definition allows. All 108 recipes of v5 respect the requested diet.

Raw summaries of every version: [results/](results/).

## What we learned

1. **The checker alone halves the violations (v1)**, and it almost removes wrong labels
   (43 % → 6 %), because broken diet tags are removed before the user sees them.
2. **Prevention beats repair (v2).** Revisions could not stop the chef from using a trap
   ingredient that is on the user's list. Telling it up front ("do not use honey, use maple
   syrup") brought violations close to zero, even without the checker.
3. **False alarms cost time (v3).** Simple keyword rules flagged correct substitutes like
   "olive oil (instead of butter)", which caused needless revisions and even dropped two
   good recipes. Making the rules understand substitutes cut the average time from 9.2 s to 7.4 s.
4. **The LLM critic matters for hidden ingredients (v4).** Rules cannot know that Caesar
   dressing contains anchovy; the critic caught it (6 % → 1 %).
5. **The judge has blind spots too (v4).** Neither the app's critic nor the judge flagged plain
   "pesto" or "kimchi" for Vegan. Found by reading the raw results, then fixed in both.

## Limitations

- One run per request per version; LLM output varies, so small differences (±1-2 recipes)
  are noise.
- The hidden-product rules of v5 were added *after* v4 found the gaps, so v5's numbers on the
  6 hidden requests are optimistic. A new, unseen set of hidden traps would be the fairer test.
- The judge is an LLM and makes mistakes (see v5); its verdicts were spot-checked by hand.
