# Market Research Report Generator

A multi-agent Python application for generating market research reports from web search results.

## Setup Steps

1. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API keys:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your API keys:
   - `GEMINI_API_KEY` — Get a free key from [Google AI Studio](https://aistudio.google.com/)
   - `TAVILY_API_KEY` — Get a free key from [Tavily](https://tavily.com/)

4. **Run the application:**

   ```bash
   python main.py "your research question"
   ```

   This runs the **full pipeline** (plan → research → write → report) by default and generates
   `reports/<topic-slug>.md`.

   ```bash
   python main.py "your research question" --research
   ```

   Runs **single-question research mode** (old behavior): searches the web and prints verified facts
   with source URLs.

   ```bash
   python main.py "your research question" --pipeline
   ```

   Same as running without a flag.

5. **Output location:** `reports/<topic-slug>.md` (added to `.gitignore`)

## Project Structure

```
market-research-agents/
├ .env.example      # Placeholder environment variables (never commit real keys)
├ .gitignore        # Ignores venv/, .env, __pycache__/, *.pyc, reports/
├ requirements.txt  # Python dependencies
├ README.md         # This file
├ main.py           # Entry point with argparse
└ app/
    ├── __init__.py
    ├── config.py     # Loads .env, exposes settings, validates keys
    ├── llm.py        # LLM wrapper (gemini | ollama | anthropic)
    ├── schemas.py    # Pydantic models: Fact, ResearchResult, Report, SectionDraft
    ├── agents/
    │   ├── __init__.py
    │   └── researcher.py  # Researcher agent: search + LLM + URL guard
    └── tools/
        ├── __init__.py
        └── search.py  # Tavily web search wrapper
```

## How It Works

1. **Search**: The researcher searches the web using Tavily (excluding YouTube, Facebook, Instagram, TikTok, X/Twitter, Pinterest).
2. **LLM Extraction**: A language model extracts structured facts from the search results, instructed to use ONLY the provided results.
3. **URL Guard**: Any fact whose `source_url` does not match a search result URL is discarded (anti-hallucination).
4. **Writing**: Sections are drafted from verified facts only, no outside knowledge or padding.
5. **Report**: Assembled into a markdown file with inline citations and a numbered Sources list.

## Week 1 Status Checklist

- [x] Project structure created
- [x] `.env.example` with all provider placeholders
- [x] `.gitignore` configured
- [x] `requirements.txt` with python-dotenv, pydantic, tavily-python, google-genai, ollama, anthropic
- [x] `app/config.py` — loads .env, exposes constants, raises clear error on missing keys
- [x] `app/schemas.py` — Pydantic models: Fact, ResearchResult, Report, SectionDraft
- [x] `app/llm.py` — ask() and ask_json() with retry and markdown stripping
- [x] `app/tools/search.py` — Tavily web search with error handling
- [x] `app/agents/researcher.py` — research() with web search, LLM call, URL anti-hallucination guard
- [x] `main.py` — argparse, clean output, logging
- [ ] TODO: Week 2 — Add UI, database, additional agents