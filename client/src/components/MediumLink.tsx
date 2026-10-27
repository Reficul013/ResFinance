const MEDIUM_ARTICLE_URL =
  "https://medium.com/@haseebshaik00/resfinance-57064e9a54ef";

export function MediumLink() {
  return (
    <a
      className="auth-button secondary medium-link"
      href={MEDIUM_ARTICLE_URL}
      target="_blank"
      rel="noreferrer"
      aria-label="Read about ResFinance on Medium"
      title="Medium"
    >
      <svg
        className="auth-action-icon medium-icon"
        viewBox="0 0 24 24"
        width="28"
        height="28"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M2 19V5h4.1l5.9 8.2L17.9 5H22v14h-4v-7.8l-5.2 7.1h-1.6L6 11.2V19H2Z" />
      </svg>
    </a>
  );
}
