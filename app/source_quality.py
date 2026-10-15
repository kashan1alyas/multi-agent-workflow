"""Source quality classification for report UI labels."""

from urllib.parse import urlparse


#: Label mapping for the UI
SOURCE_QUALITY_LABELS = {
    "official": "official",
    "academic": "academic",
    "news": "news",
    "company": "company",
    "aggregator": "aggregator",
    "unknown": "unknown",
}

#: Official domains: .gov.pk, .gov, .int, .org.pk government-style bodies
_OFFICIAL_SUFFIXES = [".gov.pk", ".gov", ".int", ".org.pk"]

#: Academic domains
_ACADEMIC_SUFFIXES = [
    ".edu",
    ".ac",
    "sciencedirect.com",
    "springer.com",
    "mdpi.com",
    "researchgate.net",
    "academia.edu",
]

#: News domains (small constant list)
_NEWS_SUFFIXES = [
    "brecorder.com",
    "dawn.com",
    "tribune.com.pk",
    "thenews.com.pk",
    "reuters.com",
    "bbc.com",
]

#: Aggregator domains
_AGGREGATOR_SUFFIXES = [
    "marketresearchreports.com",
    "market.us",
    "marketsandmarkets.com",
    "maximizemarketresearch.com",
    "stellarmr.com",
    "6wresearch.com",
    "marketdataforecast.com",
    "statista.com",
]


def _match_suffix(netloc: str, suffixes) -> bool:
    """Check if netloc ends with any of the given suffixes."""
    for s in suffixes:
        # Each suffix starts with '.', so check if netloc ends with s
        if netloc.endswith(s):
            # Make sure it's a proper domain suffix match
            # e.g., netloc "example.gov.pk" ends with ".gov.pk" -> true
            # but netloc "gov.pk" should not match if we want subdomains
            # Actually, we want: if netloc is "something.gov.pk", it should match
            # The suffix includes the leading '.', so "example.gov.pk".endswith(".gov.pk") is True
            return True
    return False


def classify(url: str) -> str:
    """Classify a source URL into one of: official, academic, news, company, aggregator, unknown."""
    parsed = urlparse(url)
    if not parsed.netloc:
        return "unknown"

    netloc = parsed.netloc.lower()
    # Remove port number if present
    if ":" in netloc:
        netloc = netloc.split(":")[0]
    # Strip trailing dots
    while netloc.endswith("."):
        netloc = netloc[:-1]
    # Remove www. prefix
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Check aggregator domains first (specific exact match or suffix match)
    for d in _AGGREGATOR_SUFFIXES:
        if _match_suffix(netloc, [d]):
            return "aggregator"

    # Check academic domains
    for d in _ACADEMIC_SUFFIXES:
        if _match_suffix(netloc, [d]):
            return "academic"

    # Check news domains
    for d in _NEWS_SUFFIXES:
        if _match_suffix(netloc, [d]):
            return "news"

    # Check official domains
    for d in _OFFICIAL_SUFFIXES:
        if _match_suffix(netloc, [d]):
            return "official"

    # Check company: any .com.pk or .com not in the lists above
    if netloc.endswith(".com.pk") or netloc.endswith(".com"):
        return "company"

    return "unknown"


def label(url: str) -> str:
    """Return the human-readable label for a source URL."""
    return SOURCE_QUALITY_LABELS.get(classify(url), "unknown")