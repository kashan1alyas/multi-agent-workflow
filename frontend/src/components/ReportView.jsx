function ReportView({ result }) {
  const sections = result?.sections || [];

  if (sections.length === 0) {
    return <p>No sections were produced.</p>;
  }

  return (
    <div>
      {sections.map((section, index) => (
        <article className="card" key={section.draft.title || index}>
          <h2>{section.draft.title}</h2>
          <span className={section.passed ? "badge ok" : "badge warn"}>
            {section.passed ? "Verified" : "Unverified"}
          </span>

          <div>
            {section.draft.content
              .split(/\n\s*\n/)
              .filter((paragraph) => paragraph.trim())
              .map((paragraph, paragraphIndex) => (
                <p key={paragraphIndex}>{paragraph}</p>
              ))}
          </div>

          {!section.passed && section.issues?.length > 0 && (
            <div>
              <strong>Issues:</strong>
              <ul>
                {section.issues.map((issue, issueIndex) => (
                  <li key={issueIndex}>
                    <strong>{issue.claim}:</strong> {issue.problem}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {section.sources?.length > 0 && (
            <div>
              <strong>Sources:</strong>
              <ul>
                {section.sources.map((source) => (
                  <li key={source}>
                    <a
                      href={source}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {source}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

export default ReportView;
