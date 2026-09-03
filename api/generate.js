// Vercel serverless function — proxies recipe generation to OpenRouter.
// The API key lives in the OPENROUTER_API_KEY env var and never reaches the browser.

const OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions';
const MODEL = 'minimax/minimax-m3:free';

const TIME_HINT = {
  quick: 'about 15 minutes',
  medium: 'about 30 minutes',
  complex: '60 minutes or more',
};

function buildPrompt(payload) {
  const {
    ingredients = [],
    portions = 2,
    people = 2,
    cookingTime = 'medium',
    cuisines = [],
    dietPreferences = [],
  } = payload || {};

  const ingredientLines = ingredients.length
    ? ingredients
        .map((i) => `- ${i.name}${i.quantity ? ` (${i.quantity}${i.unit || ''})` : ''}`)
        .join('\n')
    : '- (no specific ingredients provided — assume a basic pantry)';

  const diets = dietPreferences.filter((d) => d && d !== 'None');
  const cuisineList = cuisines.filter((c) => c && c !== 'Any');

  return [
    'Create exactly 3 distinct recipes that primarily use the ingredients below.',
    'Common pantry staples (salt, pepper, oil, water, basic spices) may be assumed.',
    '',
    'Available ingredients:',
    ingredientLines,
    '',
    `Portions per recipe: ${portions}`,
    `Cooking for: ${people} people`,
    `Target cooking time: ${TIME_HINT[cookingTime] || TIME_HINT.medium}`,
    cuisineList.length ? `Preferred cuisines: ${cuisineList.join(', ')}` : 'Cuisine: chef’s choice',
    diets.length ? `Dietary requirements (must respect all): ${diets.join(', ')}` : 'Dietary requirements: none',
    '',
    'Respond with ONLY a JSON object, no markdown, in this exact shape:',
    '{',
    '  "recipes": [',
    '    {',
    '      "name": "string",',
    '      "description": "one or two appetising sentences",',
    '      "cookTime": "e.g. \\"25 min\\"",',
    '      "cuisine": "string",',
    '      "dietTags": ["string"],',
    `      "portions": ${portions},`,
    '      "nutrition": { "calories": number, "protein": number, "carbs": number, "fat": number },',
    '      "ingredients": ["quantified ingredient line", "..."],',
    '      "instructions": ["step 1", "step 2", "..."]',
    '    }',
    '  ]',
    '}',
    'Nutrition values are per portion, in grams except calories (kcal).',
    '',
    'Instructions rules:',
    '- Give 6 to 10 steps. Each step is 1 to 3 full sentences.',
    '- Explain it plainly, the way you would tell a grandparent who is new to cooking:',
    '  say what to do, what it should look, smell or feel like, and roughly how long it takes.',
    '- Use simple everyday words. No chef jargon, no abbreviations.',
    '- Do NOT put the recipe name, cuisine, or serving count inside any step.',
    '- Do NOT number the steps yourself; just write the sentence(s).',
  ].join('\n');
}

function extractJson(text) {
  if (!text) throw new Error('Empty response from model');
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenced ? fenced[1] : text;
  const start = candidate.indexOf('{');
  const end = candidate.lastIndexOf('}');
  if (start === -1 || end === -1) throw new Error('No JSON object in model response');
  return JSON.parse(candidate.slice(start, end + 1));
}

function normalise(recipes, fallbackPortions) {
  if (!Array.isArray(recipes)) throw new Error('Model response had no "recipes" array');
  return recipes.map((r, i) => ({
    id: i + 1,
    name: String(r.name || `Recipe ${i + 1}`),
    description: String(r.description || ''),
    cookTime: String(r.cookTime || '30 min'),
    cuisine: String(r.cuisine || 'Various'),
    dietTags: Array.isArray(r.dietTags) ? r.dietTags.map(String) : [],
    portions: Number(r.portions) || fallbackPortions || 2,
    nutrition: {
      calories: Number(r?.nutrition?.calories) || 0,
      protein: Number(r?.nutrition?.protein) || 0,
      carbs: Number(r?.nutrition?.carbs) || 0,
      fat: Number(r?.nutrition?.fat) || 0,
    },
    ingredients: Array.isArray(r.ingredients) ? r.ingredients.map(String) : [],
    instructions: Array.isArray(r.instructions) ? r.instructions.map(String) : [],
  }));
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: 'OPENROUTER_API_KEY is not configured' });
  }

  const payload = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : req.body || {};

  const prompt = buildPrompt(payload);
  const ATTEMPTS = 3;
  let lastError = 'Unknown error';

  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    try {
      const orRes = await fetch(OPENROUTER_URL, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': 'https://code-a-cuisine-three.vercel.app',
          'X-Title': 'Code a Cuisine',
        },
        body: JSON.stringify({
          model: MODEL,
          temperature: 0.8,
          max_tokens: 6000,
          messages: [
            {
              role: 'system',
              content:
                'You are a professional recipe developer. You always return valid JSON matching the requested schema and never invent ingredients the user does not have beyond common pantry staples.',
            },
            { role: 'user', content: prompt },
          ],
        }),
      });

      if (!orRes.ok) {
        lastError = `OpenRouter returned ${orRes.status}: ${(await orRes.text()).slice(0, 300)}`;
        // 429/5xx are worth retrying; 4xx (bad key etc.) are not.
        if (orRes.status !== 429 && orRes.status < 500) break;
        continue;
      }

      const data = await orRes.json();
      const content = data?.choices?.[0]?.message?.content;
      const parsed = extractJson(content);
      const recipes = normalise(parsed.recipes, payload.portions);

      if (recipes.length === 0) throw new Error('Model returned an empty recipe list');

      return res.status(200).json({ recipes });
    } catch (err) {
      lastError = String(err.message || err);
      console.error(`generate attempt ${attempt}/${ATTEMPTS} failed:`, lastError);
    }
  }

  return res.status(502).json({
    error: 'Could not generate recipes right now. Please try again.',
    detail: lastError,
  });
}
