// Personal Recipe Book — persisted in the browser via localStorage.
// No mock data: the book starts empty and only holds what the user saves.

const KEY = 'cac.cookbook.v1';

export function recipeKey(recipe) {
  if (recipe.key) return recipe.key;
  const slug = String(recipe.name || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  return slug || `recipe-${Date.now()}`;
}

export function getSaved() {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function write(list) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable (private mode, quota) — nothing we can do */
  }
  window.dispatchEvent(new Event('cookbook-change'));
}

export function isSaved(key) {
  return getSaved().some((r) => r.key === key);
}

// Returns true if the recipe is saved after the call, false if it was removed.
export function toggleSave(recipe) {
  const key = recipeKey(recipe);
  const list = getSaved();
  const idx = list.findIndex((r) => r.key === key);
  if (idx >= 0) {
    list.splice(idx, 1);
    write(list);
    return false;
  }
  list.push({ ...recipe, key, savedAt: Date.now() });
  write(list);
  return true;
}
