import { useState, useMemo, useEffect } from 'react';
import RecipeCard from './RecipeCard';
import { getSaved } from '../cookbook';

const ITEMS_PER_PAGE = 10;

const CUISINES = [
  'American', 'Asian', 'French', 'Indian', 'Italian',
  'Japanese', 'Mediterranean', 'Mexican', 'Middle Eastern',
];

const TIME_FILTERS = [
  { label: 'Any time', value: '' },
  { label: 'Under 15 min', value: 15 },
  { label: 'Under 20 min', value: 20 },
  { label: 'Under 30 min', value: 30 },
  { label: 'Under 45 min', value: 45 },
  { label: 'Under 60 min', value: 60 },
];

const DIET_TAGS = [
  'Dairy-Free', 'Gluten-Free', 'Keto', 'Low-Carb',
  'Nut-Free', 'Paleo', 'Vegan', 'Vegetarian',
];

export default function CookbookPage({ onNavigate }) {
  const [selectedCuisine, setSelectedCuisine] = useState('');
  const [selectedTime, setSelectedTime] = useState('');
  const [selectedDiet, setSelectedDiet] = useState([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [saved, setSaved] = useState(getSaved);

  useEffect(() => {
    const sync = () => setSaved(getSaved());
    window.addEventListener('cookbook-change', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('cookbook-change', sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const filtered = useMemo(() => {
    return saved.filter((r) => {
      if (selectedCuisine && r.cuisine !== selectedCuisine) return false;
      if (selectedTime && parseInt(r.cookTime) > selectedTime) return false;
      if (selectedDiet.length && !selectedDiet.every((d) => r.dietTags.includes(d))) return false;
      return true;
    });
  }, [saved, selectedCuisine, selectedTime, selectedDiet]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
  const safePage = Math.min(currentPage, totalPages);
  const paginated = filtered.slice((safePage - 1) * ITEMS_PER_PAGE, safePage * ITEMS_PER_PAGE);

  const setCuisine = (val) => { setSelectedCuisine(val); setCurrentPage(1); };
  const setTime = (val) => { setSelectedTime(val); setCurrentPage(1); };
  const toggleDiet = (tag) => {
    setSelectedDiet((prev) =>
      prev.includes(tag) ? prev.filter((d) => d !== tag) : [...prev, tag]
    );
    setCurrentPage(1);
  };

  const hasActiveFilters = selectedCuisine || selectedTime || selectedDiet.length > 0;
  const clearFilters = () => {
    setSelectedCuisine('');
    setSelectedTime('');
    setSelectedDiet([]);
    setCurrentPage(1);
  };

  return (
    <section className="cookbook" aria-labelledby="cookbook-title">
      <div className="cookbook-hero">
        <h1 id="cookbook-title" className="step-title">The Recipe Book</h1>
        <p className="cookbook-desc">
          Every recipe you've saved — all in one place. Filter by cuisine,
          cooking time, or dietary preference to find exactly what you're after.
        </p>
      </div>

      <div className="cookbook-filters">
        <div className="filter-group">
          <span className="filter-label">Cuisine</span>
          <div className="chip-grid">
            <button
              className={`chip ${selectedCuisine === '' ? 'chip--active' : ''}`}
              onClick={() => setCuisine('')}
            >
              All
            </button>
            {CUISINES.map((c) => (
              <button
                key={c}
                className={`chip ${selectedCuisine === c ? 'chip--active' : ''}`}
                onClick={() => setCuisine(selectedCuisine === c ? '' : c)}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        <div className="filter-group">
          <span className="filter-label">Cooking time</span>
          <div className="chip-grid">
            {TIME_FILTERS.map((t) => (
              <button
                key={t.label}
                className={`chip ${selectedTime === t.value ? 'chip--active' : ''}`}
                onClick={() => setTime(t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div className="filter-group">
          <span className="filter-label">Dietary</span>
          <div className="chip-grid">
            {DIET_TAGS.map((tag) => (
              <button
                key={tag}
                className={`chip chip--diet ${selectedDiet.includes(tag) ? 'chip--active' : ''}`}
                onClick={() => toggleDiet(tag)}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        {hasActiveFilters && (
          <button className="btn btn--ghost cookbook-clear" onClick={clearFilters}>
            Clear all filters
          </button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="cookbook-empty">
          <p className="cookbook-empty-title">
            {saved.length === 0 ? 'Your Recipe Book is empty' : 'No recipes found'}
          </p>
          <p className="cookbook-empty-sub">
            {saved.length === 0
              ? 'Generate some recipes, then tap “Save” on any card to keep it here.'
              : 'No saved recipes match your current filters.'}
          </p>
          <div className="cookbook-empty-actions">
            <button className="btn btn--primary" onClick={() => onNavigate('generator')}>
              Go to Generator →
            </button>
            {hasActiveFilters && (
              <button className="btn btn--ghost" onClick={clearFilters}>
                Clear filters
              </button>
            )}
          </div>
        </div>
      ) : (
        <>
          <p className="cookbook-count">
            {filtered.length} recipe{filtered.length !== 1 ? 's' : ''}
            {totalPages > 1 && ` · page ${safePage} of ${totalPages}`}
          </p>

          <div className="recipe-grid">
            {paginated.map((recipe, i) => (
              <RecipeCard
                key={recipe.key || recipe.id}
                recipe={recipe}
                index={(safePage - 1) * ITEMS_PER_PAGE + i}
              />
            ))}
          </div>

          {totalPages > 1 && (
            <nav className="pagination" aria-label="Recipe pages">
              <button
                className="pagination-btn"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={safePage === 1}
                aria-label="Previous page"
              >
                ← Prev
              </button>

              <div className="pagination-pages">
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
                  <button
                    key={n}
                    className={`pagination-btn ${n === safePage ? 'pagination-btn--active' : ''}`}
                    onClick={() => setCurrentPage(n)}
                    aria-current={n === safePage ? 'page' : undefined}
                  >
                    {n}
                  </button>
                ))}
              </div>

              <button
                className="pagination-btn"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage === totalPages}
                aria-label="Next page"
              >
                Next →
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
