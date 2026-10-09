import argparse
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.planner import plan
from app.agents.researcher import research


logger = logging.getLogger(__name__)
TOPICS_FILE = Path(__file__).resolve().parent / "topics.json"
FROZEN_DIR = Path(__file__).resolve().parent / "frozen"
QUESTIONS_PER_TOPIC = 3


def slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "topic"


def load_topics() -> list[str]:
    topics = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    if not isinstance(topics, list) or not all(
        isinstance(topic, str) for topic in topics
    ):
        raise ValueError(f"{TOPICS_FILE} must contain a JSON list of topic strings")
    return topics


def freeze_topic(topic: str, output_path: Path) -> None:
    plan_result = plan(topic)
    sections = plan_result.sections[:QUESTIONS_PER_TOPIC]
    if len(sections) != QUESTIONS_PER_TOPIC:
        raise ValueError(
            f"Planner returned {len(sections)} questions; "
            f"expected at least {QUESTIONS_PER_TOPIC}"
        )

    research_results = [
        research(question=section.question, search_query=section.search_query)
        for section in sections
    ]
    frozen = {
        "topic": topic,
        "questions": [section.question for section in sections],
        "research": [
            result.model_dump(mode="json") for result in research_results
        ],
    }
    output_path.write_text(
        json.dumps(frozen, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze Planner questions and Researcher results for evaluation topics."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N topics (default: all).",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be zero or greater")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    topics = load_topics()
    if args.limit is not None:
        topics = topics[: args.limit]
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[str, str]] = []
    for topic in topics:
        output_path = FROZEN_DIR / f"{slugify(topic)}.json"
        if output_path.exists():
            logger.info("Skipping existing frozen topic: %s", output_path)
            continue

        try:
            logger.info("Freezing topic: %s", topic)
            freeze_topic(topic, output_path)
        except Exception as exc:
            logger.exception("Failed to freeze topic %r", topic)
            failures.append((topic, str(exc)))

    if failures:
        print(f"Failed to freeze {len(failures)} topic(s):")
        for topic, error in failures:
            print(f"- {topic}: {error}")
        return 1

    print(f"Completed freezing {len(topics)} topic(s); no failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
