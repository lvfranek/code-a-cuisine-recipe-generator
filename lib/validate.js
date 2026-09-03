// Server-side validation and normalisation of the /api/generate request body.
// The client enforces the same limits for instant feedback, but this is the
// real gate - never trust what arrives over the wire.

export const LIMITS = {
  maxBodyBytes: 10 * 1024, // 10 KB
  maxIngredients: 20,
  ingredientNameMax: 50,
  maxQuantity: 100000,
  maxPortions: 20,
  maxPeople: 20,
};

const UNITS = ['g', 'ml', 'oz', 'pcs', 'tsp', 'tbsp', 'cup'];
const COOKING_TIMES = ['quick', 'medium', 'complex'];
const CUISINES = [
  'Any', 'German', 'Italian', 'Indian', 'Japanese', 'Mexican',
  'French', 'Thai', 'American', 'Mediterranean', 'Other',
];
const DIETS = [
  'None', 'Vegan', 'Vegetarian', 'Keto',
  'Gluten-Free', 'Dairy-Free', 'Low-Carb', 'Paleo',
];

// Strip ASCII control chars (U+0000..U+001F and U+007F) and collapse whitespace,
// so an ingredient name can't smuggle extra lines/instructions into the prompt.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]+/g;

function cleanText(value, max) {
  return String(value ?? '')
    .replace(CONTROL_CHARS, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, max);
}

function clampInt(value, min, max, fallback) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function pickFromList(values, allowed, max) {
  if (!Array.isArray(values)) return [];
  const seen = new Set();
  const out = [];
  for (const v of values) {
    const s = String(v);
    if (allowed.includes(s) && !seen.has(s)) {
      seen.add(s);
      out.push(s);
      if (out.length >= max) break;
    }
  }
  return out;
}

// raw: already JSON-parsed body. Returns { ok, value } or { ok:false, error }.
export function validatePayload(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, error: 'Request body must be a JSON object.' };
  }

  const ingredientsIn = Array.isArray(raw.ingredients) ? raw.ingredients : [];
  if (ingredientsIn.length > LIMITS.maxIngredients) {
    return { ok: false, error: `Too many ingredients (max ${LIMITS.maxIngredients}).` };
  }

  const ingredients = [];
  for (const item of ingredientsIn) {
    if (!item || typeof item !== 'object') continue;
    const name = cleanText(item.name, LIMITS.ingredientNameMax);
    if (!name) continue;

    let quantity = Number(item.quantity);
    if (!Number.isFinite(quantity) || quantity < 0) quantity = 0;
    quantity = Math.min(quantity, LIMITS.maxQuantity);

    const unit = UNITS.includes(String(item.unit)) ? String(item.unit) : UNITS[0];
    ingredients.push({ name, quantity, unit });
  }

  if (ingredients.length === 0) {
    return { ok: false, error: 'Add at least one ingredient.' };
  }

  return {
    ok: true,
    value: {
      ingredients,
      portions: clampInt(raw.portions, 1, LIMITS.maxPortions, 2),
      people: clampInt(raw.people, 1, LIMITS.maxPeople, 2),
      cookingTime: COOKING_TIMES.includes(String(raw.cookingTime))
        ? String(raw.cookingTime)
        : 'medium',
      cuisines: pickFromList(raw.cuisines, CUISINES, CUISINES.length),
      dietPreferences: pickFromList(raw.dietPreferences, DIETS, DIETS.length),
    },
  };
}
