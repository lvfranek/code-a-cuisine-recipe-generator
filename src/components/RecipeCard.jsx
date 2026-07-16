import { useState } from 'react';

const COLORS = ['accent', 'herb', 'gold'];

export default function RecipeCard({ recipe, index = 0 }) {
  const [open, setOpen] = useState(false);
  const color = COLORS[index % 3];

  return (
    <article
      className={`recipe-card recipe-card--${color}`}
      style={{ animationDelay: `${index * 0.09}s` }}
    >
      <div className="recipe-card-header">
        <div className="recipe-meta-row">
          <span className="recipe-cuisine">{recipe.cuisine}</span>
          <span className="recipe-time">{recipe.cookTime}</span>
        </div>
        <h3 className="recipe-name">{recipe.name}</h3>
        <p className="recipe-desc">{recipe.description}</p>

        {recipe.nutrition && (
          <div className="nutrition-block">
            <div className="nutrition-row">
              <div className="nutrition-item">
                <span className="nutrition-value">{recipe.nutrition.calories}</span>
                <span className="nutrition-label">kcal</span>
              </div>
              <div className="nutrition-divider" />
              <div className="nutrition-item">
                <span className="nutrition-value">{recipe.nutrition.protein}g</span>
                <span className="nutrition-label">protein</span>
              </div>
              <div className="nutrition-divider" />
              <div className="nutrition-item">
                <span className="nutrition-value">{recipe.nutrition.carbs}g</span>
                <span className="nutrition-label">carbs</span>
              </div>
              <div className="nutrition-divider" />
              <div className="nutrition-item">
                <span className="nutrition-value">{recipe.nutrition.fat}g</span>
                <span className="nutrition-label">fat</span>
              </div>
            </div>
            <p className="nutrition-note">per portion · {recipe.portions} portion{recipe.portions !== 1 ? 's' : ''} total</p>
          </div>
        )}

        <div className="recipe-tags">
          {recipe.dietTags.map((tag) => (
            <span key={tag} className="diet-tag">{tag}</span>
          ))}
          <span className="portions-tag">{recipe.portions} portions</span>
        </div>
      </div>

      <button
        className="recipe-expand-btn"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={`recipe-body-${recipe.id}`}
      >
        {open ? 'Hide full recipe' : 'View full recipe'}
      </button>

      {open && (
        <div id={`recipe-body-${recipe.id}`} className="recipe-body">
          <div className="recipe-section">
            <h4>Ingredients</h4>
            <ul className="recipe-ingredients">
              {recipe.ingredients.map((ing, i) => (
                <li key={i}>{ing}</li>
              ))}
            </ul>
          </div>

          <div className="recipe-section">
            <h4>Instructions</h4>
            <ol className="recipe-instructions">
              {recipe.instructions.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </article>
  );
}
