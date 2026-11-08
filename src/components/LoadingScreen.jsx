import { useState, useEffect } from 'react';
import { progressState } from '../progress';

const MESSAGES = [
  'Tasting your ingredients…',
  'Consulting the kitchen…',
  'Almost ready to plate…',
  'Seasoning to perfection…',
  'Final garnish incoming…',
];

function StageIcon({ done, active }) {
  if (done) return <span className="loading-step-icon loading-step-icon--done" aria-hidden="true">✓</span>;
  if (active) return <span className="loading-step-icon loading-step-icon--active" aria-hidden="true" />;
  return <span className="loading-step-icon" aria-hidden="true" />;
}

export default function LoadingScreen({ progress = [] }) {
  const [msgIndex, setMsgIndex] = useState(0);
  const live = progress.length > 0;

  useEffect(() => {
    const id = setInterval(() => {
      setMsgIndex((i) => (i + 1) % MESSAGES.length);
    }, 2200);
    return () => clearInterval(id);
  }, []);

  const { stages, revision } = progressState(progress);
  const current = stages.find((s) => s.active);

  return (
    <div className="loading-screen" role="status" aria-label="Generating your recipes">
      {/* Steam bowl SVG animation */}
      <svg
        className="steam-bowl-svg"
        viewBox="0 0 120 110"
        fill="none"
        aria-hidden="true"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Steam wisps — animate upward with staggered delays */}
        <path
          className="steam-wisp"
          d="M37 58 Q31 46 37 35 Q43 24 37 13 Q33 6 37 2"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          className="steam-wisp"
          d="M60 58 Q54 45 60 33 Q66 21 60 10 Q56 4 60 0"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          className="steam-wisp"
          d="M83 58 Q89 46 83 35 Q77 24 83 13 Q87 6 83 2"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />

        {/* Bowl body — arc (bottom of bowl) */}
        <path
          d="M18 65 Q60 98 102 65"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
        {/* Bowl rim — subtle top arc for 3D effect */}
        <path
          d="M18 65 Q60 54 102 65"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          opacity="0.35"
        />
        {/* Left side */}
        <line x1="18" y1="65" x2="12" y2="82" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        {/* Right side */}
        <line x1="102" y1="65" x2="108" y2="82" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        {/* Base */}
        <line x1="12" y1="82" x2="108" y2="82" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>

      <div className="loading-text" aria-live="polite">
        <p className="loading-label">Code a <em>Cuisine</em></p>
        {live ? (
          <p className="loading-message" key={current?.key || 'done'}>
            {revision > 0 && current?.key === 'adapt' ? 'Fixing a diet issue…' : `${current?.label || 'Plating up'}…`}
          </p>
        ) : (
          <p className="loading-message" key={msgIndex}>
            {MESSAGES[msgIndex]}
          </p>
        )}
      </div>

      {live && (
        <ol className="loading-steps" aria-label="Progress">
          {stages.map((s) => (
            <li
              key={s.key}
              className={`loading-step${s.done ? ' loading-step--done' : ''}${s.active ? ' loading-step--active' : ''}`}
            >
              <StageIcon done={s.done} active={s.active} />
              <span>{s.label}</span>
            </li>
          ))}
          {revision > 0 && (
            <li className="loading-step loading-step--note">
              The diet check found an issue, so the chef is improving the recipes (round {revision} of 2).
            </li>
          )}
        </ol>
      )}
    </div>
  );
}
