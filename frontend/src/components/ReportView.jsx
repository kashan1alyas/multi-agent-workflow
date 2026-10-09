import { useState } from "react";

const TEXT_KEYS = ["text", "content", "body", "draft", "summary", "answer"];

// Turn any value into readable text without crashing.
function textOf(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(textOf).filter(Boolean).join("\n\n");
  }
  if (typeof value === "object") {
    for (const key of TEXT_KEYS) {
      if (typeof value[key] === "string" && value[key]) return value[key];
    }
    for (const key of TEXT_KEYS) {
      if (value[key] != null && typeof value[key] === "object") {
        const nested = textOf(value[key]);
        if (nested) return nested;
      }
    }
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function toArray(value) {
  if (Array.isArray(value)) return value;
  if (value == null || value === "") return [];
  return [value];
}

function pickVerified(s) {
  const review = s.review && typeof s.review === "object" ? s.review : {};
  const candidates = [
    s.verified,
    s.passed,
    s.approved,
    review.passed,
    review.verified,
    review.approved,
  ];
  for (const c of candidates) {
    if (typeof c === "boolean") return c;
  }
  if (typeof s.status === "string") {
    return s.status.toLowerCase() === "verified";
  }
  return false;
}

function issueText(item) {
  if (typeof item === "string") return item;
  if (item && typeof item === "object" && item.problem) {
    return item.claim ? `${item.claim}: ${item.problem}` : String(item.problem);
  }
  return textOf(item);
}

function urlOf(src) {
  if (typeof src === "string") return src;
  if (src && typeof src === "object") {
    return String(src.url || src.source_url || src.href || "");
  }
  return "";
}

function normalize(s, i) {
  const section = s && typeof s === "object" ? s : { draft: s };
  const review = section.review && typeof section.review === "object"
    ? section.review
    : {};

  return {
    question: textOf(section.question || section.title) || `Section ${i + 1}`,
    draft: textOf(section.draft ?? section.text ?? section.content),
    verified: pickVerified(section),
    sources: toArray(section.sources ?? section.source_urls)
      .map(urlOf)
      .filter(Boolean),
    issues: toArray(section.issues ?? review.issues),
  };
}

function toMarkdown(sections) {
  return sections
    .map((s) => {
      let md = `## ${s.question}\n\n*${s.verified ? "Verified" : "Unverified"}*\n\n${s.draft}\n`;

      if (!s.verified && s.issues.length > 0) {
        const lines = s.issues.map((x) => `- ${issueText(x)}`).join("\n");
        md += `\n**Reviewer issues**\n\n${lines}\n`;
      }

      if (s.sources.length > 0) {
        const lines = s.sources.map((u, n) => `${n + 1}. ${u}`).join("\n");
        md += `\n**Sources**\n\n${lines}\n`;
      }

      return md;
    })
    .join("\n");
}

export default function ReportView({ result }) {
  const [copied, setCopied] = useState(false);

  const raw = Array.isArray(result) ? result : toArray(result?.sections);
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
                  <li key={k}>{issueText(issue)}</li>
                ))}
              </ul>
            </div>
          )}

          {s.sources.length > 0 && (
            <div>
              <h3>Sources</h3>
              <ul>
                {s.sources.map((url, k) => (
                  <li key={k}>
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      {url}
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