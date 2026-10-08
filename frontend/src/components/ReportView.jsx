import { useState } from "react";

function pickVerified(s) {
  if (typeof s.verified === "boolean") return s.verified;
  if (typeof s.passed === "boolean") return s.passed;
  if (typeof s.approved === "boolean") return s.approved;
  if (typeof s.status === "string") {
    return s.status.toLowerCase() === "verified";
  }
  return false;
}

function asText(item) {
  if (typeof item === "string") return item;
  if (item && item.problem) {
    return item.claim ? `${item.claim}: ${item.problem}` : item.problem;
  }
  return JSON.stringify(item);
}

function urlOf(src) {
  return typeof src === "string" ? src : src.url;
}

function normalize(s, i) {
  return {
    question: s.question || s.title || `Section ${i + 1}`,
    draft: s.draft || s.text || s.content || "",
    verified: pickVerified(s),
    sources: s.sources || s.source_urls || [],
    issues: s.issues || [],
  };
}

function toMarkdown(sections) {
  return sections
    .map((s) => {
      let md = `## ${s.question}\n\n*${s.verified ? "Verified" : "Unverified"}*\n\n${s.draft}\n`;

      if (!s.verified && s.issues.length > 0) {
        const lines = s.issues.map((x) => `- ${asText(x)}`).join("\n");
        md += `\n**Reviewer issues**\n\n${lines}\n`;
      }

      if (s.sources.length > 0) {
        const lines = s.sources
          .map((x, n) => `${n + 1}. ${urlOf(x)}`)
          .join("\n");
        md += `\n**Sources**\n\n${lines}\n`;
      }

      return md;
    })
    .join("\n");
}

export default function ReportView({ result }) {
  const [copied, setCopied] = useState(false);

  const raw = Array.isArray(result) ? result : result?.sections || [];
  const sections = raw.map(normalize);

  if (sections.length === 0) {
    return <div className="card">No sections were produced.</div>;
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(toMarkdown(sections));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div>
      <button type="button" onClick={handleCopy}>
        {copied ? "Copied!" : "Copy report as Markdown"}
      </button>

      {sections.map((s, i) => (
        <div className="card" key={i}>
          <h2>{s.question}</h2>
          <span className={s.verified ? "badge ok" : "badge warn"}>
            {s.verified ? "Verified" : "Unverified"}
          </span>

          {s.draft.split("\n\n").map((p, j) => (
            <p key={j}>{p}</p>
          ))}

          {!s.verified && s.issues.length > 0 && (
            <div>
              <h3>Reviewer issues</h3>
              <ul>
                {s.issues.map((issue, k) => (
                  <li key={k}>{asText(issue)}</li>
                ))}
              </ul>
            </div>
          )}

          {s.sources.length > 0 && (
            <div>
              <h3>Sources</h3>
              <ul>
                {s.sources.map((src, k) => (
                  <li key={k}>
                    <a
                      href={urlOf(src)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {urlOf(src)}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}