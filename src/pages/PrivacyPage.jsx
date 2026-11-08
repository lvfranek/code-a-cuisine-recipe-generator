export default function PrivacyPage({ onNavigate }) {
  return (
    <div className="legal-page">
      <div className="legal-hero">
        <p className="legal-eyebrow">Legal</p>
        <h1 className="legal-title">Privacy Policy</h1>
        <p className="legal-subtitle">Last updated: November 2026</p>
      </div>

      <div className="legal-content">
        <section className="legal-section">
          <h2>1. Overview</h2>
          <p>
            Code a Cuisine ("we", "us", or "our") respects your privacy. This Privacy Policy
            explains what information we collect when you use our recipe generation service, how
            we use it, and your rights regarding that information.
          </p>
        </section>

        <section className="legal-section">
          <h2>2. Information We Collect</h2>
          <p>We collect only the information necessary to provide our Service:</p>
          <ul>
            <li>
              <strong>Ingredients and preferences</strong> — the ingredients, portion sizes,
              cooking time preferences, cuisine types, and dietary restrictions you enter to
              generate a recipe. This data is sent to our AI model to produce your results.
            </li>
            <li>
              <strong>Fridge photos (optional)</strong> — if you choose to scan a photo, it is
              resized in your browser and sent to our server and our AI provider only to recognise
              the ingredients in it. The photo is processed in memory and is never stored by us.
              Please do not photograph people or personal documents.
            </li>
            <li>
              <strong>Technical data for abuse protection</strong> — to enforce daily usage limits,
              our server keeps a short code derived from your IP address with a secret random key,
              together with a request counter. Your IP address itself is not stored, the code cannot
              be turned back into it, and it is deleted automatically after about one day.
            </li>
            <li>
              <strong>Usage data</strong> — basic anonymised analytics such as page visits
              and feature interactions, used to improve the Service.
            </li>
          </ul>
          <p>We do not require account registration and do not collect your name, email, or
          payment information to use the core generator.</p>
        </section>

        <section className="legal-section">
          <h2>3. How We Use Your Information</h2>
          <p>The information you provide is used to:</p>
          <ul>
            <li>Generate personalised recipes via our AI model.</li>
            <li>Improve the quality and relevance of future recipe suggestions.</li>
            <li>Analyse aggregate usage patterns to improve the Service.</li>
          </ul>
          <p>We do not sell, rent, or share your personal data with third parties for marketing purposes.</p>
        </section>

        <section className="legal-section">
          <h2>4. AI Processing</h2>
          <p>
            Ingredient and preference data, and fridge photos if you choose to scan one, are
            processed by our own server and forwarded to our AI provider (OpenRouter, which passes
            requests to the underlying model provider) to recognise ingredients and generate recipe
            content. These providers may be located outside the European Union. We only send what
            is needed for your request and require our AI providers to adhere to appropriate data
            protection standards and not use your submissions to train their models without
            consent.
          </p>
        </section>

        <section className="legal-section">
          <h2>5. Cookies and Local Storage</h2>
          <p>
            Code a Cuisine may use browser local storage to remember your ingredient list or
            preferences within a session. We do not use tracking cookies or third-party advertising
            cookies. If we introduce analytics cookies in the future, we will update this policy
            and request your consent where required by law.
          </p>
        </section>

        <section className="legal-section">
          <h2>6. Data Retention</h2>
          <p>
            Session data (ingredients, preferences and photos) is not stored on our servers after
            your request has been processed. Usage counters are deleted automatically after about one day. Anonymised analytics data may be retained for up to 12 months.
          </p>
        </section>

        <section className="legal-section">
          <h2>7. Your Rights</h2>
          <p>
            Depending on your location, you may have rights under applicable data protection laws,
            including the right to access, correct, or delete personal data we hold about you. Since
            we collect minimal identifiable information, most requests can be fulfilled by simply
            clearing your browser data. For any specific requests, contact us at the address below.
          </p>
        </section>

        <section className="legal-section">
          <h2>8. Children's Privacy</h2>
          <p>
            The Service is not directed at children under 13. We do not knowingly collect personal
            information from children. If you believe a child has provided us with personal data,
            please contact us and we will delete it promptly.
          </p>
        </section>

        <section className="legal-section">
          <h2>9. Changes to This Policy</h2>
          <p>
            We may update this Privacy Policy from time to time. We will post the revised policy
            on this page with an updated date. Your continued use of the Service after any changes
            constitutes acceptance of the new policy.
          </p>
        </section>

        <section className="legal-section">
          <h2>10. Contact Us</h2>
          <p>
            If you have questions or concerns about this Privacy Policy, please contact us at{' '}
            <a href="mailto:privacy@codeacuisine.com">privacy@codeacuisine.com</a>.
          </p>
        </section>
      </div>

      <div className="legal-footer">
        <button className="btn btn--ghost" onClick={() => onNavigate('generator')}>
          ← Back to Generator
        </button>
      </div>
    </div>
  );
}
