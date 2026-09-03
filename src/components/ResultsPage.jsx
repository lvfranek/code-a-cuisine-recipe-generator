import RecipeCard from './RecipeCard';

export default function ResultsPage({ recipes, onReset }) {
  return (
    <section className="results" aria-labelledby="results-title">
      <div className="results-header">
        <h2 id="results-title" className="step-title">Your recipes are ready</h2>
        <p className="results-count">{recipes.length} recipes crafted just for you</p>
        <button className="btn btn--ghost results-reset" onClick={onReset}>
          ← Start Over
        </button>
      </div>

      <div className="recipe-grid" role="list">
        {recipes.map((recipe, i) => (
          <div key={recipe.id} role="listitem">
            <RecipeCard recipe={recipe} index={i} />
          </div>
        ))}
      </div>
    </section>
  );
}
