import { useState } from 'react';
import './App.css';
import StepIngredients from './components/StepIngredients';
import StepPreferences from './components/StepPreferences';
import LoadingScreen from './components/LoadingScreen';
import ResultsPage from './components/ResultsPage';
import CookbookPage from './components/CookbookPage';
import TermsPage from './pages/TermsPage';
import PrivacyPage from './pages/PrivacyPage';
import LogoIcon from './components/LogoIcon';
import { generateRecipes } from './api';

const DEFAULT_PREFS = {
  portions: 2,
  people: 2,
  cookingTime: '',
  cuisines: [],
  dietPreferences: [],
};

function StepIndicator({ current }) {
  return (
    <nav className="step-indicator" aria-label="Progress steps">
      <div className={`step-dot-wrap ${current === 1 ? 'active' : 'done'}`}>
        <div
          className={`step-dot ${current === 1 ? 'step-dot--active' : 'step-dot--done'}`}
          aria-current={current === 1 ? 'step' : undefined}
        >
          {current > 1 ? '✓' : '1'}
        </div>
        <span className="step-dot-label">Ingredients</span>
      </div>
      <div
        className={`step-connector ${current > 1 ? 'step-connector--done' : ''}`}
        aria-hidden="true"
      />
      <div className={`step-dot-wrap ${current === 2 ? 'active' : ''}`}>
        <div
          className={`step-dot ${current === 2 ? 'step-dot--active' : ''}`}
          aria-current={current === 2 ? 'step' : undefined}
        >
          2
        </div>
        <span className="step-dot-label">Preferences</span>
      </div>
    </nav>
  );
}

function Navbar({ page, onNavigate }) {
  return (
    <header className="navbar">
      <div className="navbar-inner">
        <button
          className="nav-logo-btn"
          onClick={() => onNavigate('generator')}
          aria-label="Code a Cuisine — go to generator"
        >
          <LogoIcon className="nav-logo-icon" />
          <span className="nav-logo">Code a <em>Cuisine</em></span>
        </button>
        <nav className="navbar-nav">
          <button
            className={`btn--nav ${page === 'generator' ? 'btn--nav-active' : ''}`}
            onClick={() => onNavigate('generator')}
            aria-current={page === 'generator' ? 'page' : undefined}
          >
            Generator
          </button>
          <button
            className={`btn--nav ${page === 'cookbook' ? 'btn--nav-active' : ''}`}
            onClick={() => onNavigate('cookbook')}
            aria-current={page === 'cookbook' ? 'page' : undefined}
          >
            Recipe Book
          </button>
        </nav>
      </div>
    </header>
  );
}

function Footer({ onNavigate }) {
  const year = new Date().getFullYear();
  return (
    <footer className="footer">
      <div className="footer-body">
        <div className="footer-brand">
          <div className="footer-logo">
            <LogoIcon className="footer-logo-icon" />
            <span>Code a <em>Cuisine</em></span>
          </div>
          <p className="footer-desc">
            Tell us what's in your kitchen and we'll give you recipes
            you can cook with what you already have.
          </p>
        </div>
      </div>
      <div className="footer-divider" aria-hidden="true" />
      <div className="footer-bottom">
        <p className="footer-copy">
          © {year} Code a Cuisine. All rights reserved.
        </p>
        <nav className="footer-legal" aria-label="Legal links">
          <button className="footer-legal-link" onClick={() => onNavigate('privacy')}>
            Privacy Policy
          </button>
          <span aria-hidden="true">·</span>
          <button className="footer-legal-link" onClick={() => onNavigate('terms')}>
            Terms of Service
          </button>
        </nav>
      </div>
    </footer>
  );
}

function GeneratorFlow({ screen, setScreen, ingredients, setIngredients, preferences, setPreferences, recipes, setRecipes }) {
  const [genError, setGenError] = useState('');

  const handleGenerate = async () => {
    setGenError('');
    setScreen('loading');
    const payload = {
      ingredients: ingredients.map(({ name, quantity, unit }) => ({ name, quantity, unit })),
      ...preferences,
    };
    try {
      const data = await generateRecipes(payload);
      if (!data?.recipes?.length) throw new Error('No recipes were returned. Please try again.');
      setRecipes(data.recipes);
      setScreen('results');
    } catch (err) {
      console.error('Recipe generation failed:', err);
      setGenError(err.message || 'Something went wrong. Please try again.');
      setScreen('preferences');
    }
  };

  const handleReset = () => {
    setGenError('');
    setIngredients([]);
    setPreferences(DEFAULT_PREFS);
    setRecipes([]);
    setScreen('ingredients');
  };

  if (screen === 'loading') {
    return <LoadingScreen />;
  }

  const stepNum = screen === 'preferences' ? 2 : screen === 'ingredients' ? 1 : null;

  return (
    <>
      {stepNum !== null && <StepIndicator current={stepNum} />}
      <main className="app-main">
        <div key={screen} className={`screen-enter${screen === 'ingredients' ? ' screen-enter--hero' : ''}`}>
          {screen === 'ingredients' && (
            <StepIngredients
              ingredients={ingredients}
              setIngredients={setIngredients}
              onNext={() => setScreen('preferences')}
            />
          )}
          {screen === 'preferences' && (
            <StepPreferences
              preferences={preferences}
              setPreferences={setPreferences}
              onBack={() => setScreen('ingredients')}
              onGenerate={handleGenerate}
              error={genError}
            />
          )}
          {screen === 'results' && (
            <ResultsPage recipes={recipes} onReset={handleReset} />
          )}
        </div>
      </main>
    </>
  );
}

export default function App() {
  const [page, setPage] = useState('generator');
  const [screen, setScreen] = useState('ingredients');
  const [ingredients, setIngredients] = useState([]);
  const [preferences, setPreferences] = useState(DEFAULT_PREFS);
  const [recipes, setRecipes] = useState([]);

  const handleNavigate = (destination) => {
    setPage(destination);
  };

  const isCookbook = page === 'cookbook';

  return (
    <div className="app">
      <Navbar page={page} onNavigate={handleNavigate} />

      {page === 'generator' && (
        <GeneratorFlow
          screen={screen}
          setScreen={setScreen}
          ingredients={ingredients}
          setIngredients={setIngredients}
          preferences={preferences}
          setPreferences={setPreferences}
          recipes={recipes}
          setRecipes={setRecipes}
        />
      )}

      {isCookbook && (
        <main className="app-main">
          <div className="screen-enter screen-enter--cookbook">
            <CookbookPage onNavigate={handleNavigate} />
          </div>
        </main>
      )}

      {page === 'terms' && (
        <main className="app-main">
          <div className="screen-enter screen-enter--legal">
            <TermsPage onNavigate={handleNavigate} />
          </div>
        </main>
      )}

      {page === 'privacy' && (
        <main className="app-main">
          <div className="screen-enter screen-enter--legal">
            <PrivacyPage onNavigate={handleNavigate} />
          </div>
        </main>
      )}

      <Footer onNavigate={handleNavigate} />
    </div>
  );
}
