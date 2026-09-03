import { useState } from 'react';

const UNITS = ['g', 'ml', 'oz', 'pcs', 'tsp', 'tbsp', 'cup'];

const FEATURES = [
  { label: 'Pantry-based',  sub: 'Zero waste cooking'      },
  { label: 'AI-crafted',    sub: 'Three recipes, instantly' },
  { label: 'Diet-aware',    sub: 'Personalised results'     },
];

export default function StepIngredients({ ingredients, setIngredients, onNext }) {
  const [name, setName]           = useState('');
  const [quantity, setQuantity]   = useState('');
  const [unit, setUnit]           = useState('g');
  const [editingId, setEditingId] = useState(null);
  const [editValues, setEditValues] = useState({});

  const canAdd = name.trim().length > 0 && quantity !== '';

  const handleAdd = () => {
    if (!canAdd) return;
    setIngredients((prev) => [
      ...prev,
      { id: Date.now(), name: name.trim(), quantity: Number(quantity), unit },
    ]);
    setName('');
    setQuantity('');
    setUnit('g');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleAdd();
  };

  const handleRemove = (id) => {
    setIngredients((prev) => prev.filter((i) => i.id !== id));
    if (editingId === id) setEditingId(null);
  };

  const startEdit = (ingredient) => {
    setEditingId(ingredient.id);
    setEditValues({ name: ingredient.name, quantity: ingredient.quantity, unit: ingredient.unit });
  };

  const saveEdit = (id) => {
    if (!editValues.name.trim()) return;
    setIngredients((prev) =>
      prev.map((i) =>
        i.id === id
          ? { ...i, name: editValues.name.trim(), quantity: Number(editValues.quantity), unit: editValues.unit }
          : i
      )
    );
    setEditingId(null);
  };

  const cancelEdit = () => setEditingId(null);

  const handleEditKeyDown = (e, id) => {
    if (e.key === 'Enter') saveEdit(id);
    if (e.key === 'Escape') cancelEdit();
  };

  const ingredientCount = ingredients.length;
  const countLabel = ingredientCount === 0
    ? 'Add at least one ingredient to continue.'
    : `${ingredientCount} ingredient${ingredientCount !== 1 ? 's' : ''} added`;

  return (
    <div className="step-hero">

      {/* ── LEFT — editorial ── */}
      <div className="step-hero-left">
        <h2 className="step-hero-title" id="step1-title">
          Cook with<br />what you have.
        </h2>

        <p className="step-hero-body">
          Add the ingredients sitting in your kitchen and we'll craft
          three personalised recipes — no extra shopping required.
        </p>
        <p className="step-hero-body">
          Once they're ready, you can save the ones you like to your Recipe Book.
        </p>

        <div className="step-hero-features">
          {FEATURES.map((f) => (
            <div key={f.label} className="step-feature">
              <span className="step-feature-dot" aria-hidden="true" />
              <div>
                <p className="step-feature-label">{f.label}</p>
                <p className="step-feature-sub">{f.sub}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── RIGHT — floating card ── */}
      <section className="step-hero-card" aria-labelledby="step1-title">

        <div className="step-card-head">
          <h3 className="step-card-title">What's in your kitchen?</h3>
          <p className="step-card-subtitle" aria-live="polite">{countLabel}</p>
        </div>

        {/* Input form */}
        <div className="ingredient-form">
          <div className="ingredient-inputs">
            <div className="field">
              <label htmlFor="ing-name">Ingredient</label>
              <input
                id="ing-name"
                type="text"
                placeholder="e.g. chicken breast"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={handleKeyDown}
                autoComplete="off"
              />
            </div>
            <div className="field field--qty">
              <label htmlFor="ing-qty">Qty</label>
              <input
                id="ing-qty"
                type="number"
                placeholder="300"
                min="0"
                step="any"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                onKeyDown={handleKeyDown}
              />
            </div>
            <div className="field field--narrow">
              <label htmlFor="ing-unit">Unit</label>
              <select
                id="ing-unit"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
              >
                {UNITS.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </div>
            <button
              className="btn btn--add"
              onClick={handleAdd}
              disabled={!canAdd}
              aria-label="Add ingredient to list"
            >
              + Add
            </button>
          </div>
        </div>

        {/* Ingredient list */}
        {ingredientCount > 0 && (
          <ul className="ingredient-list" role="list" aria-label="Added ingredients">
            {ingredients.map((ingredient) => (
              <li key={ingredient.id} className="ingredient-item">
                {editingId === ingredient.id ? (
                  <div className="ingredient-edit">
                    <input
                      className="edit-input"
                      value={editValues.name}
                      onChange={(e) => setEditValues((v) => ({ ...v, name: e.target.value }))}
                      onKeyDown={(e) => handleEditKeyDown(e, ingredient.id)}
                      aria-label="Ingredient name"
                      autoFocus
                    />
                    <input
                      className="edit-input edit-input--narrow"
                      type="number"
                      min="0"
                      step="any"
                      value={editValues.quantity}
                      onChange={(e) => setEditValues((v) => ({ ...v, quantity: e.target.value }))}
                      onKeyDown={(e) => handleEditKeyDown(e, ingredient.id)}
                      aria-label="Quantity"
                    />
                    <select
                      className="edit-select"
                      value={editValues.unit}
                      onChange={(e) => setEditValues((v) => ({ ...v, unit: e.target.value }))}
                      aria-label="Unit"
                    >
                      {UNITS.map((u) => (
                        <option key={u} value={u}>{u}</option>
                      ))}
                    </select>
                    <div className="edit-actions">
                      <button className="btn btn--confirm" onClick={() => saveEdit(ingredient.id)}>
                        Save
                      </button>
                      <button className="btn--cancel-edit" onClick={cancelEdit}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <span className="ingredient-label">
                      <strong>{ingredient.name}</strong>
                      <span className="ingredient-qty">{ingredient.quantity} {ingredient.unit}</span>
                    </span>
                    <div className="ingredient-actions">
                      <button
                        className="btn--icon"
                        onClick={() => startEdit(ingredient)}
                        aria-label={`Edit ${ingredient.name}`}
                      >
                        Edit
                      </button>
                      <button
                        className="btn--danger"
                        onClick={() => handleRemove(ingredient.id)}
                        aria-label={`Remove ${ingredient.name}`}
                      >
                        Remove
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}

        {/* Footer */}
        <div className="step-card-footer">
          <button
            className="btn btn--primary"
            onClick={onNext}
            disabled={ingredientCount === 0}
            aria-disabled={ingredientCount === 0}
          >
            Next →
          </button>
        </div>

      </section>
    </div>
  );
}
