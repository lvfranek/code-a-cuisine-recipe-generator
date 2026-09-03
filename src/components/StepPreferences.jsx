const CUISINES = [
  'Any',
  'German', 'Italian', 'Indian', 'Japanese', 'Mexican',
  'French', 'Thai', 'American', 'Mediterranean', 'Other',
];

const DIETS = [
  'None', 'Vegan', 'Vegetarian', 'Keto',
  'Gluten-Free', 'Dairy-Free', 'Low-Carb', 'Paleo',
];

const COOKING_TIMES = [
  { id: 'quick',   label: 'Quick',   time: '~15 min' },
  { id: 'medium',  label: 'Medium',  time: '~30 min' },
  { id: 'complex', label: 'Complex', time: '~60+ min' },
];

export default function StepPreferences({ preferences, setPreferences, onBack, onGenerate, error }) {
  const update = (key, value) =>
    setPreferences((prev) => ({ ...prev, [key]: value }));

  const toggleCuisine = (c) => {
    if (c === 'Any') {
      update('cuisines', ['Any']);
      return;
    }
    const without = preferences.cuisines.filter((x) => x !== 'Any');
    update(
      'cuisines',
      without.includes(c)
        ? without.filter((x) => x !== c)
        : [...without, c]
    );
  };

  const canGenerate =
    Boolean(preferences.cookingTime) &&
    preferences.cuisines.length > 0 &&
    preferences.dietPreferences.length > 0;

  const toggleDiet = (d) => {
    if (d === 'None') {
      update('dietPreferences', ['None']);
      return;
    }
    const without = preferences.dietPreferences.filter((x) => x !== 'None');
    update(
      'dietPreferences',
      without.includes(d)
        ? without.filter((x) => x !== d)
        : [...without, d]
    );
  };

  return (
    <section className="step" aria-labelledby="step2-title">
      <h2 id="step2-title" className="step-title">Set your preferences</h2>
      <p className="step-description">Tailor the recipes to your exact needs.</p>

      {/* Portions & People */}
      <div className="pref-group">
        <h3 className="pref-group-title">Portions &amp; people</h3>
        <div className="pref-row">
          <div className="stepper-field">
            <label id="portions-label">How many portions?</label>
            <div className="stepper" role="group" aria-labelledby="portions-label">
              <button
                onClick={() => update('portions', Math.max(1, preferences.portions - 1))}
                aria-label="Decrease portions"
              >
                −
              </button>
              <span aria-live="polite" aria-atomic="true">{preferences.portions}</span>
              <button
                onClick={() => update('portions', preferences.portions + 1)}
                aria-label="Increase portions"
              >
                +
              </button>
            </div>
          </div>

          <div className="stepper-field">
            <label id="people-label">Cooking for how many?</label>
            <div className="stepper" role="group" aria-labelledby="people-label">
              <button
                onClick={() => update('people', Math.max(1, preferences.people - 1))}
                aria-label="Decrease number of people"
              >
                −
              </button>
              <span aria-live="polite" aria-atomic="true">{preferences.people}</span>
              <button
                onClick={() => update('people', preferences.people + 1)}
                aria-label="Increase number of people"
              >
                +
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Cooking Time */}
      <div className="pref-group">
        <h3 className="pref-group-title">Cooking time</h3>
        <div className="time-cards" role="group" aria-label="Select cooking time">
          {COOKING_TIMES.map((t) => (
            <button
              key={t.id}
              className={`time-card ${preferences.cookingTime === t.id ? 'time-card--active' : ''}`}
              onClick={() => update('cookingTime', t.id)}
              aria-pressed={preferences.cookingTime === t.id}
            >
              <span className="time-card-label">{t.label}</span>
              <span className="time-card-time">{t.time}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Cuisine */}
      <div className="pref-group">
        <h3 className="pref-group-title">Cuisine</h3>
        <div className="chip-grid" role="group" aria-label="Select cuisines">
          {CUISINES.map((c) => (
            <button
              key={c}
              className={`chip ${preferences.cuisines.includes(c) ? 'chip--active' : ''}`}
              onClick={() => toggleCuisine(c)}
              aria-pressed={preferences.cuisines.includes(c)}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Diet */}
      <div className="pref-group">
        <h3 className="pref-group-title">Diet preferences</h3>
        <div className="chip-grid" role="group" aria-label="Select diet preferences">
          {DIETS.map((d) => (
            <button
              key={d}
              className={`chip chip--diet ${preferences.dietPreferences.includes(d) ? 'chip--active' : ''}`}
              onClick={() => toggleDiet(d)}
              aria-pressed={preferences.dietPreferences.includes(d)}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="step-error" role="alert">
          {error}
        </p>
      )}

      {!error && !canGenerate && (
        <p className="step-hint" role="status">
          Choose a cooking time, a cuisine, and a diet preference to continue.
        </p>
      )}

      <div className="step-footer step-footer--split">
        <button className="btn btn--ghost" onClick={onBack}>
          ← Back
        </button>
        <button
          className="btn btn--primary"
          onClick={onGenerate}
          disabled={!canGenerate}
        >
          Generate Recipes →
        </button>
      </div>
    </section>
  );
}
